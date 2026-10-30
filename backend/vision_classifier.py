"""
Boots Bundle Image Studio — Vision Classifier
=============================================
Uses a Gemini vision model to look at a bundle's ORIGINAL Boots.com image and
decide whether it needs fixing, applying the catalogue rules:
  - shows only one product unit but a multiplier badge implies several
  - has an overlaid number/multiplier badge (x3, x5)
  - blurry / low-res / non-white background / products touching

This is image -> text analysis (reliable), NOT image editing. It is the only
way to tell a GOOD single-type multipack (shows all units) from a BAD one
(shows one unit + badge), which have identical metadata.
"""

from __future__ import annotations

import json
import logging
import os
from io import BytesIO

from PIL import Image

logger = logging.getLogger(__name__)

_PROMPT = (
    "You are auditing a Boots.com product-bundle image for an e-commerce catalogue. "
    "Reply with ONLY compact JSON (no markdown fences), exactly these keys:\n"
    '{"usable_product_image":bool,"has_number_badge":bool,"shows_one_unit_with_badge":bool,'
    '"products_overlapping":bool,"poor_image_quality":bool,"needs_fixing":bool,"reason":"<=14 words"}\n'
    "Definitions:\n"
    "- usable_product_image: false if it is a placeholder / loading spinner / 'image coming soon' "
    "/ broken or missing image rather than a real product photo.\n"
    "- has_number_badge: ONLY a clearly OVERLAID promotional multiplier sticker — a distinct circle, "
    "star-burst or rounded badge, usually brightly coloured, containing a number like '3', 'x3', 'x5' — "
    "that has been placed ON TOP of the photo (not part of any product). It does NOT count if the number "
    "is printed on the product's own packaging/label, is a size or volume (e.g. '200ml', '2x75g'), is a "
    "percentage, or is part of the pack design. If you are not clearly seeing an overlaid multiplier "
    "sticker, set this false.\n"
    "- shows_one_unit_with_badge: only ONE product unit is visible, yet an overlaid multiplier badge "
    "(as defined above) implies several. If two or more distinct product units are visible, set false.\n"
    "- products_overlapping: the products touch or overlap with no clear gap between them, but the photo "
    "is otherwise clean (sharp, white background). This is purely a spacing issue.\n"
    "- poor_image_quality: a GENUINE image-quality problem — blurry, low-resolution, pixelated, a "
    "watermark, heavy clutter, or a non-white / photographic / busy background. Products merely touching "
    "on a clean white background is NOT poor_image_quality (use products_overlapping for that).\n"
    "- needs_fixing: true if (has_number_badge OR shows_one_unit_with_badge OR products_overlapping OR "
    "poor_image_quality) AND usable_product_image is true. If usable_product_image is false, set false."
)


_VERIFY_PROMPT = (
    "Image A is the ORIGINAL product-bundle photo from a retail website. Image B is a "
    "REBUILT version that should show the very same products, just spaced out on a white "
    "background. Check Image B against Image A. Reply with ONLY compact JSON (no markdown "
    "fences), exactly these keys:\n"
    '{"same_products":bool,"same_count":bool,"no_added_marks":bool,"text_intact":bool,'
    '"no_overlap":bool,"reason":"<=16 words"}\n'
    "- same_products: B shows the same product variants as A — same packaging design, "
    "colours, brand and product names. A different variant, flavour, design, an open jar "
    "instead of a closed one, a swatch or placeholder instead of the product = false.\n"
    "- same_count: B shows the same number of product units as A (ignore any multiplier "
    "badge in A; count the physical units the bundle should contain).\n"
    "- no_added_marks: B has no sticker, tag, price/size box, badge or text that is not "
    "part of the products in A.\n"
    "- text_intact: the label text in B is legible and spelled like A. Slight softness is "
    "fine; set false only if words are clearly misspelled, scrambled or nonsense.\n"
    "- no_overlap: products in B do not overlap each other."
)


class VisionUnavailable(Exception):
    """Gemini can't be used at all (credits used up / invalid key). Processing
    must stop with a clear message instead of silently falling back to weaker
    logic that produces bad images."""


def _raise_if_unavailable(e: Exception) -> None:
    msg = str(e)
    low = msg.lower()
    if "402" in msg or "credits are depleted" in low or "api key not valid" in low:
        raise VisionUnavailable(
            "Gemini is unavailable — the API credits are used up or the key is invalid. "
            "Top up at https://ai.studio/projects, then click Re-check."
        ) from e


class VisionClassifier:
    """Classifies a bundle's original image against the catalogue rules."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model or os.getenv("VISION_MODEL", "gemini-3-flash-preview")
        from google import genai
        from google.genai import types
        self._types = types
        self.client = genai.Client(api_key=self.api_key)
        # Deterministic answers: the same image must get the same verdict on
        # every run (otherwise bundles flip between "fine" and "needs fixing").
        self._config = types.GenerateContentConfig(temperature=0)
        logger.info(f"VisionClassifier using model: {self.model}")

    def classify(self, image_path: str) -> dict | None:
        """Return a verdict dict, or None if the model call fails."""
        try:
            img = Image.open(image_path).convert("RGB")
            img.thumbnail((900, 900))  # smaller = faster + cheaper, still legible
            buf = BytesIO()
            img.save(buf, "JPEG", quality=90)
            resp = self.client.models.generate_content(
                model=self.model,
                config=self._config,
                contents=[
                    self._types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg"),
                    _PROMPT,
                ],
            )
            txt = (resp.text or "").strip().replace("```json", "").replace("```", "").strip()
            d = json.loads(txt)
            usable = bool(d.get("usable_product_image", True))
            return {
                "usable": usable,
                "has_badge": bool(d.get("has_number_badge", False)),
                "single_with_badge": bool(d.get("shows_one_unit_with_badge", False)),
                "overlapping": bool(d.get("products_overlapping", False)),
                "poor_quality": bool(d.get("poor_image_quality", False)),
                "needs_fixing": usable and bool(d.get("needs_fixing", False)),
                "reason": str(d.get("reason", ""))[:140],
            }
        except (json.JSONDecodeError, ValueError, OSError) as e:
            logger.warning(f"Vision classify parse/IO error for {image_path}: {e}")
            return None
        except Exception as e:  # noqa: BLE001 — never let one image break the batch
            _raise_if_unavailable(e)
            logger.warning(f"Vision classify failed for {image_path}: {e}")
            return None

    def _jpeg_part(self, path: str, max_dim: int):
        img = Image.open(path).convert("RGB")
        img.thumbnail((max_dim, max_dim))
        buf = BytesIO()
        img.save(buf, "JPEG", quality=90)
        return self._types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg")

    def verify(self, original_path: str, rebuilt_path: str) -> dict | None:
        """Compare a rebuilt bundle image to the original. Returns
        {ok, reason, ...checks} or None if the model call fails."""
        try:
            resp = self.client.models.generate_content(
                model=self.model,
                config=self._config,
                contents=[
                    "Image A (original):", self._jpeg_part(original_path, 1100),
                    "Image B (rebuilt):", self._jpeg_part(rebuilt_path, 1100),
                    _VERIFY_PROMPT,
                ],
            )
            txt = (resp.text or "").strip().replace("```json", "").replace("```", "").strip()
            d = json.loads(txt)
            checks = {k: bool(d.get(k, False)) for k in
                      ("same_products", "same_count", "no_added_marks", "text_intact", "no_overlap")}
            return {**checks, "ok": all(checks.values()), "reason": str(d.get("reason", ""))[:160]}
        except (json.JSONDecodeError, ValueError, OSError) as e:
            logger.warning(f"Vision verify parse/IO error for {rebuilt_path}: {e}")
            return None
        except Exception as e:  # noqa: BLE001 — never let one image break the batch
            _raise_if_unavailable(e)
            logger.warning(f"Vision verify failed for {rebuilt_path}: {e}")
            return None
