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

import os
import io
import json
import zipfile
import logging
import shutil
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from pydantic import BaseModel

# Import our modules
from monday_client import MondayClient
from boots_crawler import BootsCrawler
from image_composer import ImageComposer
from gemini_client import GeminiClient
from bundle_processor import BundleProcessor

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
ROUNDEL_PATH = os.path.join(os.path.dirname(__file__), "roundel.png")
os.makedirs(UPLOADS_DIR, exist_ok=True)

# Environment variables
MONDAY_API_TOKEN = os.getenv("MONDAY_API_TOKEN", "")
MONDAY_BOARD_ID = os.getenv("MONDAY_BOARD_ID", "5100428483")
BOOTS_X_AGENT_CLIENT = os.getenv("BOOTS_X_AGENT_CLIENT", "W-7njoVr89mFAk")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")

# In-memory storage for approved bundles (simple — no database needed for v1)
# In production, this could be replaced with a database or file-based store
approved_bundles: dict[str, dict] = {}  # code -> {code, title, image_path, approved_at}
bundle_data_cache: list[dict] = []  # Cache of last fetched bundle data

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
    allow_credentials=True,
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
    gap: Optional[int] = None


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
    """Create a MondayClient instance from environment variables."""
    if not MONDAY_API_TOKEN:
        raise HTTPException(status_code=500, detail="MONDAY_API_TOKEN not configured")
    return MondayClient(api_token=MONDAY_API_TOKEN, board_id=MONDAY_BOARD_ID)


def get_crawler() -> BootsCrawler:
    """Create a BootsCrawler instance."""
    return BootsCrawler(x_agent_client=BOOTS_X_AGENT_CLIENT)


def get_composer() -> ImageComposer:
    """Create an ImageComposer instance."""
    return ImageComposer(roundel_path=ROUNDEL_PATH if os.path.exists(ROUNDEL_PATH) else None)


def get_gemini_client() -> GeminiClient:
    """Create a GeminiClient instance."""
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")
    return GeminiClient(api_key=GEMINI_API_KEY)


def get_processor() -> BundleProcessor:
    """Create a BundleProcessor instance."""
    return BundleProcessor()


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

@app.get("/api/bundles")
async def get_bundles(refresh: bool = Query(False, description="Force re-fetch from Monday.com")):
    """
    Fetch all bundles from Monday.com, crawl Boots.com for images,
    assess quality, categorize, and return structured data for the frontend.

    Args:
        refresh: If True, force re-fetch even if cached data exists.
    """
    global bundle_data_cache

    if bundle_data_cache and not refresh:
        logger.info("Returning cached bundle data")
        return {"bundles": bundle_data_cache, "count": len(bundle_data_cache)}

    try:
        monday = get_monday_client()
        crawler = get_crawler()
        composer = get_composer()
        processor = get_processor()

        # Step 1: Fetch confirmed live bundles from Monday.com
        logger.info("Fetching bundles from Monday.com...")
        bundles = await monday.get_confirmed_live_bundles()
        logger.info(f"Found {len(bundles)} confirmed live bundles")

        # Step 2: Process all bundles (quality assessment + categorization + generation)
        logger.info("Processing bundles...")
        results = await processor.process_bundles(
            bundles=bundles,
            crawler=crawler,
            composer=composer,
            uploads_dir=UPLOADS_DIR,
        )

        # Step 3: Cache results
        bundle_data_cache = results
        logger.info(f"Returning {len(results)} processed bundles")
        return {"bundles": results, "count": len(results)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch bundles: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch bundles: {str(e)}")


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
        logger.error(f"Failed to fetch bundle {code}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch bundle: {str(e)}")


@app.post("/api/generate")
async def generate_image(request: GenerateRequest):
    """
    Compose a bundle image from individual product photos using PIL.
    This is the deterministic, 100% fidelity method — no AI involved.
    """
    try:
        composer = get_composer()
        output_path = os.path.join(UPLOADS_DIR, f"{request.bundle_code}_generated.jpg")

        # Validate product image paths exist
        valid_paths = [p for p in request.product_image_paths if os.path.exists(p)]
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
        logger.error(f"Failed to generate image: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Image generation failed: {str(e)}")


@app.post("/api/edit")
async def edit_image(request: EditRequest):
    """
    Edit a bundle image based on natural language instructions.

    Strategy:
    1. Try programmatic edit first (PIL — instant, 100% fidelity)
    2. If the prompt can't be handled programmatically, use Gemini API
    3. If Gemini fails, return an error with a meaningful message
    """
    try:
        composer = get_composer()
        output_path = os.path.join(UPLOADS_DIR, f"{request.bundle_code}_edited.jpg")

        # Step 1: Try programmatic edit first
        prompt_lower = request.edit_prompt.lower().strip()
        programmatic_keywords = [
            "add space", "add gap", "increase gap", "more space", "increase space",
            "reduce space", "reduce gap", "move closer", "less space", "decrease gap",
            "bigger", "larger", "increase size", "scale up",
            "smaller", "decrease size", "scale down", "too big", "too large", "reduce size",
            "center", "centre",
        ]

        is_programmatic = any(kw in prompt_lower for kw in programmatic_keywords)

        if is_programmatic:
            logger.info(f"Using PIL for programmatic edit: '{request.edit_prompt[:60]}'")
            result_path = composer.edit_bundle_image(
                current_image_path=request.image_path,
                edit_prompt=request.edit_prompt,
                output_path=output_path,
            )
            return {
                "status": "success",
                "bundle_code": request.bundle_code,
                "image_path": result_path,
                "method": "pil_programmatic",
            }

        # Step 2: Use Gemini for AI-powered edits
        logger.info(f"Using Gemini for AI edit: '{request.edit_prompt[:60]}'")
        gemini = get_gemini_client()

        result_path = gemini.edit_image(
            image_path=request.image_path,
            prompt=request.edit_prompt,
            output_path=output_path,
            reference_images=request.reference_image_paths if request.reference_image_paths else None,
        )

        # Step 3: Run a basic fidelity check
        fidelity = gemini.check_fidelity(request.image_path, result_path)
        if not fidelity["passed"]:
            logger.warning(f"Fidelity check failed for {request.bundle_code}: {fidelity['issues']}")
            return {
                "status": "success_with_warnings",
                "bundle_code": request.bundle_code,
                "image_path": result_path,
                "method": "gemini_ai",
                "warnings": fidelity["issues"],
            }

        return {
            "status": "success",
            "bundle_code": request.bundle_code,
            "image_path": result_path,
            "method": "gemini_ai",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to edit image: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Image edit failed: {str(e)}")


@app.post("/api/approve")
async def approve_image(request: ApproveRequest):
    """
    Mark a bundle image as approved.
    The image will be included in the ZIP export with the correct 8-digit bundle code as filename.
    """
    from datetime import datetime, timezone

    if not os.path.exists(request.image_path):
        raise HTTPException(status_code=400, detail=f"Image not found: {request.image_path}")

    approved_bundles[request.bundle_code] = {
        "code": request.bundle_code,
        "title": request.title,
        "image_path": request.image_path,
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }

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
            "Content-Disposition": f"attachment; filename=approved_bundle_images.zip"
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
    file: UploadFile = File(...),
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
    with open(upload_path, "wb") as f:
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
    logger.info("=" * 60)
    logger.info("Boots Bundle Image Studio API starting up...")
    logger.info(f"  Monday.com Board ID: {MONDAY_BOARD_ID}")
    logger.info(f"  Uploads directory: {UPLOADS_DIR}")
    logger.info(f"  Gemini API key: {'configured' if GEMINI_API_KEY else 'NOT SET'}")
    logger.info(f"  Monday API token: {'configured' if MONDAY_API_TOKEN else 'NOT SET'}")
    logger.info(f"  CORS origins: {CORS_ORIGINS}")
    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# Run the app
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)