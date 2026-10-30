"""
Boots Bundle Image Studio — FastAPI Server
==========================================
The main backend server that ties together all modules:
  - monday_client.py  (fetch bundle data from Monday.com)
  - boots_crawler.py  (download images from Boots.com)
  - image_composer.py (PIL compositing — deterministic, 100% fidelity)
  - gemini_client.py  (AI image editing via Google Gemini API)
  - bundle_processor.py (quality assessment + categorization)

Endpoints:
  GET  /healthz           — liveness check
  GET  /readyz            — readiness check (verifies API keys)
  GET  /api/bundles       — fetch all bundles, assess quality, categorize
  POST /api/generate      — compose a bundle image from product photos (PIL)
  POST /api/edit          — edit a bundle image (PIL first, Gemini fallback)
  POST /api/approve       — mark a bundle image as approved
  POST /api/reject        — send a bundle back to manual review
  GET  /api/export        — export all approved images as ZIP
  GET  /api/bundle/{code} — get details for a specific bundle
  POST /api/upload        — upload a supplier-provided image

Run locally:
  uvicorn app:app --host 0.0.0.0 --port 8000 --reload

Run on Render:
  uvicorn app:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import time
import zipfile

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from PIL import Image
from pydantic import BaseModel

# Load variables from a local .env file for development (no-op in production,
# where Render/Vercel inject env vars directly).
load_dotenv()

# Import our modules
from boots_crawler import BootsCrawler
from bundle_processor import BundleProcessor
from gemini_client import GeminiClient
from image_composer import ImageComposer
from monday_client import MondayClient
from vision_classifier import VisionClassifier

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Directories
UPLOADS_DIR = os.getenv("UPLOADS_DIR", "uploads")
ORIGINALS_DIR = os.getenv("ORIGINALS_DIR", "originals")  # cached Monday spreadsheets
ROUNDEL_PATH = os.path.join(os.path.dirname(__file__), "roundel.png")
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(ORIGINALS_DIR, exist_ok=True)

# File-backed store so approvals survive process restarts (the in-memory dict
# alone is lost whenever Render restarts/sleeps the service).
APPROVED_STORE = os.path.join(UPLOADS_DIR, "_approved.json")

# Environment variables
MONDAY_API_TOKEN = os.getenv("MONDAY_API_TOKEN", "")
MONDAY_BOARD_ID = os.getenv("MONDAY_BOARD_ID", "5100428483")
BOOTS_X_AGENT_CLIENT = os.getenv("BOOTS_X_AGENT_CLIENT", "W-7njoVr89mFAk")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
VISION_MODEL = os.getenv("VISION_MODEL", "gemini-3-flash-preview")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
# Browsers reject `Access-Control-Allow-Origin: *` together with credentials,
# so only allow credentials when explicit origins are configured.
CORS_ALLOW_CREDENTIALS = CORS_ORIGINS != ["*"]

# In-memory storage for approved bundles (simple — no database needed for v1)
# In production, this could be replaced with a database or file-based store
approved_bundles: dict[str, dict] = {}  # code -> {code, title, image_path, approved_at}
bundle_data_cache: list[dict] = []  # Cache of last fetched bundle data

# Background bundle-load state. The Monday download + parse + Boots.com crawl is
# slow, so it runs in a background task and /api/bundles reports progress instead
# of blocking the (single-worker) server — which would also stall /healthz.
_bundle_load: dict = {
    "status": "idle",       # idle | loading | ready | error
    "phase": "",
    "processed": 0,
    "total": 0,             # target number of defects to collect this run
    "found": 0,             # defective bundles found so far
    "scanned": 0,           # bundles scanned so far
    "live_total": 0,        # total confirmed-live bundles found
    "error": None,
    "started_at": None,
    "finished_at": None,
}
_bundle_task = None
_crawler = None  # shared BootsCrawler (pooled HTTP client), created lazily
_classifier = None  # shared VisionClassifier, created lazily

# ---------------------------------------------------------------------------
# Initialize FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Boots Bundle Image Studio API",
    description="Backend API for the Boots Bundle Image Studio web application.",
    version="1.0.0",
)

# CORS — allow the Vercel frontend to make requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=CORS_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Pydantic models for request validation
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    bundle_code: str
    product_image_paths: list[str]
    quantities: list[int] = []
    gap: int | None = None


class EditRequest(BaseModel):
    bundle_code: str
    image_path: str
    edit_prompt: str
    reference_image_paths: list[str] = []


class ApproveRequest(BaseModel):
    bundle_code: str
    image_path: str
    title: str = ""


class RejectRequest(BaseModel):
    bundle_code: str
    reason: str = ""


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def get_monday_client() -> MondayClient:
    """Create a MondayClient instance from environment variables.
    The API token isn't required in local-files testing mode (no download)."""
    if not MONDAY_API_TOKEN and not USE_LOCAL_FILES:
        raise HTTPException(status_code=500, detail="MONDAY_API_TOKEN not configured")
    return MondayClient(api_token=MONDAY_API_TOKEN, board_id=MONDAY_BOARD_ID)


def get_crawler() -> BootsCrawler:
    """Return the shared BootsCrawler (one pooled HTTP client, reused across loads)."""
    global _crawler
    if _crawler is None:
        _crawler = BootsCrawler(x_agent_client=BOOTS_X_AGENT_CLIENT, cache_dir=ORIGINALS_DIR)
    return _crawler


def get_composer() -> ImageComposer:
    """Create an ImageComposer instance."""
    return ImageComposer(roundel_path=ROUNDEL_PATH if os.path.exists(ROUNDEL_PATH) else None)


def get_classifier() -> VisionClassifier | None:
    """Return the shared VisionClassifier, or None if no Gemini key is set.

    When it's None the processor falls back to its structural catalogue rules,
    so the pipeline still runs — just without image-based badge detection.
    """
    global _classifier
    if not GEMINI_API_KEY:
        return None
    if _classifier is None:
        try:
            _classifier = VisionClassifier(api_key=GEMINI_API_KEY, model=VISION_MODEL)
        except Exception as e:  # noqa: BLE001 — missing SDK must not break loading
            logger.warning(f"VisionClassifier unavailable: {e}")
            return None
    return _classifier


def get_gemini_client() -> GeminiClient:
    """Create a GeminiClient instance."""
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")
    return GeminiClient(api_key=GEMINI_API_KEY)


def get_gemini_optional() -> GeminiClient | None:
    """A GeminiClient for background processing, or None if it isn't configured
    (processing then skips the AI-separation step instead of failing)."""
    if not GEMINI_API_KEY:
        return None
    try:
        return GeminiClient(api_key=GEMINI_API_KEY)
    except Exception as e:  # noqa: BLE001 — missing SDK must not break loading
        logger.warning(f"Gemini unavailable for processing: {e}")
        return None


def get_processor() -> BundleProcessor:
    """Create a BundleProcessor instance."""
    return BundleProcessor()


def safe_upload_path(path: str) -> str | None:
    """Resolve a client-supplied path and confirm it stays inside UPLOADS_DIR.

    Returns the absolute path if safe, otherwise None. This prevents path
    traversal / arbitrary local file reads through the paths that /api/generate,
    /api/edit, and /api/approve accept from the frontend.
    """
    uploads_abs = os.path.abspath(UPLOADS_DIR)
    target = os.path.abspath(path)
    try:
        if os.path.commonpath([uploads_abs, target]) != uploads_abs:
            return None
    except ValueError:
        # Paths on different drives (Windows) raise ValueError.
        return None
    return target


def resize_to_match(image_path: str, reference_path: str) -> None:
    """Resize image_path to the dimensions of reference_path (best-effort).
    Gemini returns a fixed-size image (~1024x1024); matching the source keeps
    edited images consistent with the rest of the pipeline and avoids a spurious
    'dimensions changed' fidelity warning."""
    try:
        with Image.open(reference_path) as ref:
            size = ref.size
        with Image.open(image_path) as edited:
            if edited.size != size:
                edited.convert("RGB").resize(size, Image.LANCZOS).save(
                    image_path, "JPEG", quality=95,
                )
    except (OSError, ValueError) as e:
        logger.warning(f"Could not resize edited image to source size: {e}")


def load_approved() -> dict:
    """Load the persisted approved-bundles store from disk."""
    try:
        with open(APPROVED_STORE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_approved() -> None:
    """Persist the approved-bundles store to disk (best-effort)."""
    try:
        with open(APPROVED_STORE, "w") as f:
            json.dump(approved_bundles, f)
    except OSError as e:
        logger.warning(f"Could not persist approved bundles: {e}")


# ---------------------------------------------------------------------------
# Health check endpoints (required by Render)
# ---------------------------------------------------------------------------

@app.get("/healthz")
async def healthz():
    """Liveness check — always returns 200 if the process is running."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    """Readiness check — verifies that required API keys are loaded."""
    issues = []
    if not MONDAY_API_TOKEN:
        issues.append("MONDAY_API_TOKEN not set")
    if not GEMINI_API_KEY:
        issues.append("GEMINI_API_KEY not set")
    if issues:
        return JSONResponse(
            status_code=503,
            content={"status": "not ready", "issues": issues}
        )
    return {"status": "ready", "services": {"monday": bool(MONDAY_API_TOKEN), "gemini": bool(GEMINI_API_KEY)}}


# ---------------------------------------------------------------------------
# Main API endpoints
# ---------------------------------------------------------------------------

# How many DEFECTIVE bundles to collect before stopping (the review set). We
# scan the confirmed-live list in chunks and stop as soon as we've found this
# many, so the first batch is quick instead of processing a fixed count.
DEFAULT_BUNDLE_LIMIT = int(os.getenv("BUNDLE_TARGET_DEFECTS", "25"))
# Hard ceiling on how many defective bundles to show, and how many to scan.
BUNDLE_MAX_SHOW = int(os.getenv("BUNDLE_MAX_SHOW", "30"))
BUNDLE_MAX_SCAN = int(os.getenv("BUNDLE_MAX_SCAN", "250"))
BUNDLE_SCAN_CHUNK = int(os.getenv("BUNDLE_SCAN_CHUNK", "15"))
# Testing toggle: skip the Monday.com download and parse the local files in
# ORIGINALS_DIR instead (also bypasses the confirmed-live cache so parsing runs).
USE_LOCAL_FILES = os.getenv("USE_LOCAL_FILES", "").strip().lower() in ("1", "true", "yes")

# Optional fixed demo/test set. When set, /api/bundles uses these codes directly
# and skips Monday.com entirely (no 45MB download or parse) — the WCS crawler
# supplies each bundle's title, components, and quantities from the code.
# Default is EMPTY: pull the real Monday.com confirmed-live list and classify a
# real batch. Set TEST_BUNDLE_CODES="10359241,..." to pin a specific demo set.
TEST_BUNDLE_CODES = [
    c.strip() for c in os.getenv("TEST_BUNDLE_CODES", "").split(",") if c.strip()
]
# Processed-results cache lifetime in seconds. 0 (default) = keep the current
# set until the reviewer asks for a "New batch", so the bundles they're working
# on never silently change underneath them.
BUNDLE_CACHE_TTL = int(os.getenv("BUNDLE_CACHE_TTL", "0"))


def _bundles_payload() -> dict:
    """Build the /api/bundles response from the current load state."""
    s = _bundle_load
    elapsed = round(time.time() - s["started_at"], 1) if s["started_at"] else 0
    ready = s["status"] == "ready"
    return {
        "status": s["status"],
        "phase": s["phase"],
        "processed": s["processed"],
        "total": s["total"],
        "found": s["found"],
        "scanned": s["scanned"],
        "live_total": s["live_total"],
        "elapsed_seconds": elapsed,
        "error": s["error"],
        "bundles": bundle_data_cache if ready else [],
        "count": len(bundle_data_cache) if ready else 0,
    }


async def _confirmed_live(refresh: bool) -> list:
    """Return the confirmed-live bundle list to process.

    Default/demo path: use the fixed TEST_BUNDLE_CODES directly and skip Monday.com
    entirely (no 45MB download or parse) — the crawler fills in title/components.
    When refresh=True, or TEST_BUNDLE_CODES is empty, fetch the real list from
    Monday.com (local files are reused unless refresh forces a download).
    """
    if TEST_BUNDLE_CODES and not refresh:
        _bundle_load["phase"] = "Loading test bundles…"
        return [{"code": c, "title": "", "products": []} for c in TEST_BUNDLE_CODES]

    def _phase(msg: str) -> None:
        _bundle_load["phase"] = msg

    monday = get_monday_client()
    return await monday.get_confirmed_live_bundles(
        refresh=refresh, originals_dir=ORIGINALS_DIR, phase_cb=_phase,
        use_local_files=USE_LOCAL_FILES,
    )


def _cached_bundle_set(cache_path: str) -> tuple[list, int]:
    """The bundles currently on the dashboard (memory first, then the cache
    file), plus the live total they came from."""
    if bundle_data_cache:
        return list(bundle_data_cache), _bundle_load.get("live_total") or len(bundle_data_cache)
    try:
        with open(cache_path) as f:
            cached = json.load(f)
        bundles = cached.get("bundles", [])
        return bundles, cached.get("live_total", len(bundles))
    except (OSError, json.JSONDecodeError):
        return [], 0


async def _reprocess_job(cache_path: str) -> bool:
    """Re-run the latest rules on the bundles ALREADY on the dashboard — no new
    search, no new bundles. Returns False if there is no cached set to reuse."""
    global bundle_data_cache
    current, live_total = _cached_bundle_set(cache_path)
    if not current:
        return False
    batch = [{"code": b["code"], "title": b.get("title", ""), "products": []} for b in current]
    _bundle_load.update(
        phase="Re-checking the current bundles with the latest rules…",
        total=len(batch), processed=0, found=0, scanned=0, live_total=live_total,
    )

    def _cb(done: int, _total: int) -> None:
        _bundle_load.update(processed=done, scanned=done)

    fresh = await get_processor().process_bundles(
        bundles=batch, crawler=get_crawler(), composer=get_composer(),
        uploads_dir=UPLOADS_DIR, progress_cb=_cb,
        classifier=get_classifier(), gemini=get_gemini_optional(), max_concurrency=4,
        force_fix=True,
    )
    # Keep the set stable: a bundle that still can't be improved keeps its
    # previous card instead of vanishing from the dashboard.
    by_code = {r["code"]: r for r in fresh}
    results = [by_code.get(b["code"], b) for b in current]
    bundle_data_cache = results
    try:
        with open(cache_path, "w") as f:  # noqa: ASYNC230 — small cache write
            json.dump({"bundles": results, "live_total": live_total}, f)
    except OSError as e:
        logger.warning(f"Could not write bundle cache: {e}")
    _bundle_load.update(
        status="ready", phase="Done", processed=len(results), found=len(results),
        finished_at=time.time(),
    )
    logger.info(f"Reprocessed {len(batch)} cached bundles -> {len(results)} need action")
    return True


async def _load_bundles_job(refresh: bool, limit: int, force: bool,
                            reprocess: bool = False) -> None:
    """Background job: resolve bundles, crawl Boots.com, compose, cache results."""
    global bundle_data_cache
    cache_path = os.path.join(UPLOADS_DIR, "_bundle_cache.json")
    try:
        # 0) Reprocess mode: improve the bundles already shown, find no new ones.
        if reprocess and await _reprocess_job(cache_path):
            return

        # 1) Serve the processed-results cache for instant repeat loads (unless
        #    a refresh or force bypass is requested).
        if not force and not refresh and os.path.exists(cache_path):
            age = time.time() - os.path.getmtime(cache_path)
            if BUNDLE_CACHE_TTL <= 0 or age < BUNDLE_CACHE_TTL:
                try:
                    with open(cache_path) as f:  # noqa: ASYNC230 — small cache read
                        cached = json.load(f)
                    bundle_data_cache = cached.get("bundles", [])
                    _bundle_load.update(
                        status="ready", phase="Done",
                        live_total=cached.get("live_total", len(bundle_data_cache)),
                        processed=len(bundle_data_cache), total=len(bundle_data_cache),
                        finished_at=time.time(),
                    )
                    logger.info(f"Served {len(bundle_data_cache)} bundles from cache ({age:.0f}s old)")
                    return
                except (json.JSONDecodeError, OSError):
                    pass

        crawler = get_crawler()
        composer = get_composer()
        processor = get_processor()

        # 2) Resolve the bundle set (test codes if set — otherwise Monday.com)
        confirmed = await _confirmed_live(refresh)
        _bundle_load["live_total"] = len(confirmed)
        target = min(limit, BUNDLE_MAX_SHOW)
        # Sample evenly across the whole confirmed list rather than taking the
        # first N. Monday rows are grouped by product family, so the first N are
        # often near-duplicates (e.g. all nappy bags) — an even stride gives the
        # reviewer a varied spread.
        max_scan = min(len(confirmed), BUNDLE_MAX_SCAN)
        if len(confirmed) > max_scan:
            step = len(confirmed) / max_scan
            scan_list = [confirmed[int(i * step)] for i in range(max_scan)]
        else:
            scan_list = confirmed
        _bundle_load.update(
            phase="Reviewing bundle images & rebuilding where needed…",
            total=target, processed=0, found=0, scanned=0,
        )
        logger.info(f"Resolved {len(confirmed)} bundles; scanning up to {len(scan_list)} "
                    f"for {target} defects")

        # 3) Scan in chunks and STOP as soon as we've collected `target` defects,
        #    so the first batch is quick instead of processing a fixed count.
        classifier = get_classifier()
        gemini = get_gemini_optional()
        results: list = []
        scanned = 0
        for start in range(0, len(scan_list), BUNDLE_SCAN_CHUNK):
            piece = scan_list[start:start + BUNDLE_SCAN_CHUNK]
            chunk_results = await processor.process_bundles(
                bundles=piece, crawler=crawler, composer=composer,
                uploads_dir=UPLOADS_DIR, classifier=classifier, gemini=gemini,
            )
            results.extend(chunk_results)
            scanned += len(piece)
            _bundle_load.update(
                found=len(results), scanned=scanned, processed=min(len(results), target),
            )
            if len(results) >= target:
                break
        results = results[:BUNDLE_MAX_SHOW]
        bundle_data_cache = results
        try:
            with open(cache_path, "w") as f:  # noqa: ASYNC230 — small cache write
                json.dump({"bundles": results, "live_total": len(confirmed)}, f)
        except OSError as e:
            logger.warning(f"Could not write bundle cache: {e}")

        _bundle_load.update(
            status="ready", phase="Done", processed=len(results), finished_at=time.time(),
        )
        logger.info(f"Bundle load complete: {len(results)} of {len(confirmed)}")
    except Exception as e:
        detail = getattr(e, "detail", None) or str(e)
        logger.exception("Bundle load failed")
        _bundle_load.update(status="error", error=detail, finished_at=time.time())


@app.get("/api/bundles")
async def get_bundles(
    refresh: bool = Query(False, description="Re-fetch the full list from Monday.com"),
    force: bool = Query(False, description="Bypass the processed-results cache and reprocess"),
    reprocess: bool = Query(
        False, description="Re-run the latest rules on the bundles already shown (no new search)",
    ),
    limit: int = Query(
        DEFAULT_BUNDLE_LIMIT, ge=1, le=500,
        description="How many defective bundles to collect before stopping",
    ),
):
    """
    Return bundles, loading them in the background so the request never blocks.

    Scans the confirmed-live list in chunks and stops once it has collected
    `limit` defective bundles (default 25), and serves a cached result when one
    is fresh (<1h) — so repeat loads are near-instant.
    Poll until `status` is `"ready"`, then `bundles` is populated.
      - `refresh=true`: re-fetch the real confirmed-live list from Monday.com.
      - `force=true`: bypass the processed-results cache and scan a new batch.
      - `reprocess=true`: re-run the latest rules on the bundles already shown.
    """
    global _bundle_task

    # Serve in-memory cached results immediately (unless a reload is requested).
    if (_bundle_load["status"] == "ready" and bundle_data_cache
            and not refresh and not force and not reprocess):
        return _bundles_payload()

    # A load already running: just report progress (don't start another).
    if _bundle_load["status"] == "loading":
        return _bundles_payload()

    # Start a new background load (first load, retry after error, refresh, or force).
    _bundle_load.update(
        status="loading", phase="Warming up…", processed=0, total=0,
        error=None, started_at=time.time(), finished_at=None,
    )
    _bundle_task = asyncio.create_task(
        _load_bundles_job(refresh=refresh, limit=limit, force=force, reprocess=reprocess),
    )
    return _bundles_payload()


@app.get("/api/bundle/{code}")
async def get_bundle(code: str):
    """Get details for a specific bundle by its 8-digit code."""
    # Check cache first
    for bundle in bundle_data_cache:
        if bundle.get("code") == code:
            return bundle

    # If not in cache, try fetching from Monday.com
    try:
        monday = get_monday_client()
        bundles = await monday.get_confirmed_live_bundles()
        for bundle in bundles:
            if bundle.get("code") == code:
                return bundle
        raise HTTPException(status_code=404, detail=f"Bundle {code} not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to fetch bundle {code}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch bundle: {e!s}")


@app.post("/api/generate")
async def generate_image(request: GenerateRequest):
    """
    Compose a bundle image from individual product photos using PIL.
    This is the deterministic, 100% fidelity method — no AI involved.
    """
    try:
        composer = get_composer()
        output_path = os.path.join(UPLOADS_DIR, f"{request.bundle_code}_generated.jpg")

        # Validate product image paths exist and stay within the uploads dir
        valid_paths = []
        for p in request.product_image_paths:
            safe = safe_upload_path(p)
            if safe and os.path.exists(safe):
                valid_paths.append(safe)
        if not valid_paths:
            raise HTTPException(
                status_code=400,
                detail="No valid product image paths provided"
            )

        quantities = request.quantities if request.quantities else [1] * len(valid_paths)

        result_path = composer.compose_bundle_image(
            product_images=valid_paths,
            output_path=output_path,
            quantities=quantities,
            gap=request.gap,
        )

        return {
            "status": "success",
            "bundle_code": request.bundle_code,
            "image_path": result_path,
            "method": "pil_compositing",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to generate image")
        raise HTTPException(status_code=500, detail=f"Image generation failed: {e!s}")


@app.post("/api/edit")
async def edit_image(request: EditRequest):
    """
    Edit a bundle image using ONLY the Gemini API (no PIL editing — PIL can only
    resize the whole image as a flat block, it can't re-compose). The fidelity
    preamble is applied inside the Gemini client.
    """
    try:
        # Validate the source image path stays within the uploads dir
        safe_image = safe_upload_path(request.image_path)
        if not safe_image or not os.path.exists(safe_image):
            raise HTTPException(status_code=400, detail=f"Invalid image path: {request.image_path}")
        safe_refs = [
            s for s in (safe_upload_path(p) for p in request.reference_image_paths)
            if s and os.path.exists(s)
        ]

        gemini = get_gemini_client()
        output_path = os.path.join(UPLOADS_DIR, f"{request.bundle_code}_edited.jpg")

        logger.info(f"Gemini AI edit for {request.bundle_code}: '{request.edit_prompt[:60]}'")
        result_path = gemini.edit_image(
            image_path=safe_image,
            prompt=request.edit_prompt,
            output_path=output_path,
            reference_images=safe_refs or None,
        )

        # Keep the edited image the same size as the source (Gemini returns ~1024px)
        resize_to_match(result_path, safe_image)

        fidelity = gemini.check_fidelity(safe_image, result_path)
        response = {
            "status": "success",
            "bundle_code": request.bundle_code,
            "image_path": result_path,
            "method": "gemini_ai",
            "fidelity_passed": fidelity["passed"],
        }
        if not fidelity["passed"]:
            logger.warning(f"Fidelity warnings for {request.bundle_code}: {fidelity['issues']}")
            response["warnings"] = fidelity["issues"]
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to edit image")
        raise HTTPException(status_code=500, detail=f"Image edit failed: {e!s}")


@app.post("/api/approve")
async def approve_image(request: ApproveRequest):
    """
    Mark a bundle image as approved.
    The image will be included in the ZIP export with the correct 8-digit bundle code as filename.
    """
    from datetime import datetime, timezone

    safe_image = safe_upload_path(request.image_path)
    if not safe_image or not os.path.exists(safe_image):
        raise HTTPException(status_code=400, detail=f"Image not found: {request.image_path}")

    approved_bundles[request.bundle_code] = {
        "code": request.bundle_code,
        "title": request.title,
        "image_path": safe_image,
        "approved_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017 — keep 3.9+ compatibility
    }
    save_approved()

    logger.info(f"Approved bundle: {request.bundle_code} — {request.title}")
    return {
        "status": "approved",
        "bundle_code": request.bundle_code,
        "approved_count": len(approved_bundles),
    }


@app.post("/api/reject")
async def reject_image(request: RejectRequest):
    """Send a bundle back to manual review."""
    if request.bundle_code in approved_bundles:
        del approved_bundles[request.bundle_code]
        save_approved()
        logger.info(f"Rejected (un-approved) bundle: {request.bundle_code}")

    logger.info(f"Bundle {request.bundle_code} sent to manual review: {request.reason}")
    return {
        "status": "rejected",
        "bundle_code": request.bundle_code,
        "reason": request.reason,
    }


@app.get("/api/export")
async def export_approved():
    """
    Export all approved bundle images as a ZIP file.
    Each image is named with the correct 8-digit Boots bundle code.
    """
    if not approved_bundles:
        raise HTTPException(status_code=404, detail="No approved bundles to export")

    # Create a ZIP file in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for code, data in approved_bundles.items():
            image_path = data["image_path"]
            if os.path.exists(image_path):
                # Use the 8-digit bundle code as the filename
                filename = f"{code}.jpg"
                zip_file.write(image_path, filename)
                logger.info(f"Added to ZIP: {filename}")

    zip_buffer.seek(0)

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": "attachment; filename=approved_bundle_images.zip"
        },
    )


@app.get("/api/approved")
async def get_approved():
    """Get a list of all currently approved bundles."""
    return {
        "approved": list(approved_bundles.values()),
        "count": len(approved_bundles),
    }


@app.post("/api/upload")
async def upload_image(
    bundle_code: str = Form(...),
    file: UploadFile = File(...),  # noqa: B008 — required FastAPI dependency idiom
):
    """
    Upload a supplier-provided image for a bundle.
    The uploaded image replaces the generated image for that bundle.
    """
    # Validate file type
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    # Validate file size (max 20MB)
    contents = await file.read()
    if len(contents) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 20MB)")

    # Save the uploaded file
    file_ext = os.path.splitext(file.filename or "image.jpg")[1] or ".jpg"
    upload_path = os.path.join(UPLOADS_DIR, f"{bundle_code}_uploaded{file_ext}")
    with open(upload_path, "wb") as f:  # noqa: ASYNC230 — small one-shot write
        f.write(contents)

    logger.info(f"Uploaded image for bundle {bundle_code}: {upload_path}")
    return {
        "status": "success",
        "bundle_code": bundle_code,
        "image_path": upload_path,
    }


@app.get("/api/images/{filename}")
async def serve_image(filename: str):
    """Serve an image file from the uploads directory."""
    # Prevent path traversal
    safe_filename = os.path.basename(filename)
    image_path = os.path.join(UPLOADS_DIR, safe_filename)
    if not os.path.exists(image_path):
        raise HTTPException(status_code=404, detail=f"Image not found: {safe_filename}")
    return FileResponse(image_path, media_type="image/jpeg")


# ---------------------------------------------------------------------------
# Startup event
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup_event():
    approved_bundles.update(load_approved())
    logger.info("=" * 60)
    logger.info("Boots Bundle Image Studio API starting up...")
    logger.info(f"  Restored {len(approved_bundles)} approved bundle(s) from disk")
    logger.info(f"  Monday.com Board ID: {MONDAY_BOARD_ID}")
    logger.info(f"  Uploads directory: {UPLOADS_DIR}")
    logger.info(f"  Gemini API key: {'configured' if GEMINI_API_KEY else 'NOT SET'}")
    logger.info(f"  Monday API token: {'configured' if MONDAY_API_TOKEN else 'NOT SET'}")
    logger.info(f"  CORS origins: {CORS_ORIGINS}")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    """Close the shared crawler's pooled HTTP client on shutdown."""
    global _crawler
    if _crawler is not None:
        await _crawler.close()
        _crawler = None


# ---------------------------------------------------------------------------
# Run the app
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)