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
    '"poor_quality_or_overlapping":bool,"needs_fixing":bool,"reason":"<=14 words"}\n'
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
    "- poor_quality_or_overlapping: blurry, low-resolution, cluttered, a non-white background, or products "
    "touching/overlapping with no visible gap.\n"
    "- needs_fixing: true if (has_number_badge OR shows_one_unit_with_badge OR poor_quality_or_overlapping) "
    "AND usable_product_image is true. If usable_product_image is false, set needs_fixing to false."
)


class VisionClassifier:
    """Classifies a bundle's original image against the catalogue rules."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model or os.getenv("VISION_MODEL", "gemini-3-flash-preview")
        from google import genai
        from google.genai import types
        self._types = types
        self.client = genai.Client(api_key=self.api_key)
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
                "poor_quality": bool(d.get("poor_quality_or_overlapping", False)),
                "needs_fixing": usable and bool(d.get("needs_fixing", False)),
                "reason": str(d.get("reason", ""))[:140],
            }
        except (json.JSONDecodeError, ValueError, OSError) as e:
            logger.warning(f"Vision classify parse/IO error for {image_path}: {e}")
            return None
        except Exception as e:  # noqa: BLE001 — never let one image break the batch
            logger.warning(f"Vision classify failed for {image_path}: {e}")
            return None
