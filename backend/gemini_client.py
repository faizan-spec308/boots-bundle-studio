"""
Boots Bundle Image Studio — Gemini Client
==========================================
Google Gemini API integration for AI-powered image editing.
Uses the google-genai Python SDK with the Nano Banana 2.1 model.

Primary image generation is done by PIL (image_composer.py) for 100% fidelity.
Gemini is used as a fallback for edits that can't be done programmatically —
e.g. "remove the background from this product", "adjust the lighting", etc.

Every Gemini call includes strict product fidelity instructions to prevent
the model from altering colours, artwork, text, proportions, or branding.
"""

from __future__ import annotations

import base64
import logging
import os
from io import BytesIO

from PIL import Image

logger = logging.getLogger(__name__)

# Fidelity preamble prepended to every Gemini prompt
FIDELITY_PREAMBLE = """CRITICAL PRODUCT FIDELITY RULES — FOLLOW EXACTLY:
- Preserve each product's original packaging, colours, labels, logos, text, and branding EXACTLY as shown.
- Do NOT redesign, redraw, stylise, or reinterpret any product.
- Do NOT stretch, compress, widen, shorten, or distort any packaging.
- Preserve the RELATIVE SIZES of the products: a smaller product must stay smaller and a larger product larger, exactly as in the original — do NOT make all products the same size.
- Do NOT invent, remove, duplicate, or alter product features.
- Use the provided reference images as visual ground truth for product appearance.
- Product accuracy takes precedence over visual creativity.
- Keep all products on a clean, pure white background (#FFFFFF).
- Maintain a clearly visible gap between products — they must NOT touch or overlap.

EDIT INSTRUCTION:
"""


class GeminiError(Exception):
    """Raised when a Gemini image operation fails after all retries."""


class GeminiClient:
    """
    Client for Google Gemini API image editing operations.
    
    Model: gemini-nano-banana-2.1 (recommended for new projects)
    SDK: google-genai (official Google Gen AI SDK for Python)
    """

    def __init__(self, api_key: str | None = None):
        """
        Initialize the Gemini client.

        Args:
            api_key: Google Gemini API key. If not provided, reads from GEMINI_API_KEY env var.
        """
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not provided and not found in environment variables")

        try:
            from google import genai
            from google.genai import types
            self.genai = genai
            self.types = types
        except ImportError:
            raise ImportError(
                "google-genai package not installed. "
                "Install with: pip install google-genai"
            )

        # Initialize the client
        self.client = genai.Client(api_key=self.api_key)
        # "Nano Banana" = Gemini 2.5 Flash Image. Overridable via env in case your
        # account needs a different id (e.g. a preview or the Pro image variant).
        self.model = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
        logger.info(f"GeminiClient initialized with model: {self.model}")

    def edit_image(
        self,
        image_path: str,
        prompt: str,
        output_path: str,
        reference_images: list[str] | None = None,
    ) -> str:
        """
        Edit an image using Gemini's image-to-image editing capability.

        Args:
            image_path: Path to the current bundle image to edit.
            prompt: Natural language edit instruction from the user.
            output_path: Where to save the edited image.
            reference_images: Optional list of individual product photo paths
                              to use as visual ground truth for product fidelity.

        Returns:
            Path to the saved edited image.

        Raises:
            Exception if the edit fails after retries.
        """
        full_prompt = FIDELITY_PREAMBLE + prompt
        max_retries = 3

        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"Gemini edit attempt {attempt}/{max_retries}: '{prompt[:80]}...'")

                # Build the content parts: start with the current image
                current_image = Image.open(image_path).convert("RGB")
                parts = [self.types.Part.from_bytes(
                    data=self._image_to_bytes(current_image),
                    mime_type="image/jpeg",
                )]

                # Add reference images if provided (for multi-reference editing)
                if reference_images:
                    for ref_path in reference_images:
                        if os.path.exists(ref_path):
                            ref_img = Image.open(ref_path).convert("RGB")
                            parts.append(self.types.Part.from_bytes(
                                data=self._image_to_bytes(ref_img),
                                mime_type="image/jpeg",
                            ))
                    full_prompt += "\n\nThe additional images provided are reference photos of the individual products. Use them to ensure product fidelity — match their exact colours, packaging, labels, and branding."

                # Add the text prompt
                parts.append(full_prompt)

                # Call the Gemini API
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=parts,
                )

                # Extract the edited image from the response
                edited_image = self._extract_image_from_response(response)
                if edited_image is None:
                    raise ValueError("Gemini response did not contain an image")

                # Save the edited image
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                edited_image.save(output_path, "JPEG", quality=95)
                logger.info(f"Gemini edit successful, saved to: {output_path}")
                return output_path

            except Exception as e:
                logger.warning(f"Gemini edit attempt {attempt} failed: {e}")
                if attempt == max_retries:
                    raise GeminiError(
                        f"Gemini image edit failed after {max_retries} attempts. "
                        f"Last error: {e}"
                    ) from e

    def generate_from_prompt(
        self,
        prompt: str,
        output_path: str,
        reference_images: list[str] | None = None,
    ) -> str:
        """
        Generate a new image from a text prompt (text-to-image).
        Used as a fallback when no suitable product images are available.

        Args:
            prompt: Text description of the desired image.
            output_path: Where to save the generated image.
            reference_images: Optional reference images to guide generation.

        Returns:
            Path to the saved generated image.
        """
        full_prompt = FIDELITY_PREAMBLE + prompt
        max_retries = 3

        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"Gemini generate attempt {attempt}/{max_retries}")

                parts = []
                if reference_images:
                    for ref_path in reference_images:
                        if os.path.exists(ref_path):
                            ref_img = Image.open(ref_path).convert("RGB")
                            parts.append(self.types.Part.from_bytes(
                                data=self._image_to_bytes(ref_img),
                                mime_type="image/jpeg",
                            ))
                    full_prompt += "\n\nUse the provided images as reference for product appearance."

                parts.append(full_prompt)

                response = self.client.models.generate_content(
                    model=self.model,
                    contents=parts,
                )

                generated_image = self._extract_image_from_response(response)
                if generated_image is None:
                    raise ValueError("Gemini response did not contain an image")

                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                generated_image.save(output_path, "JPEG", quality=95)
                logger.info(f"Gemini generate successful, saved to: {output_path}")
                return output_path

            except Exception as e:
                logger.warning(f"Gemini generate attempt {attempt} failed: {e}")
                if attempt == max_retries:
                    raise GeminiError(
                        f"Gemini image generation failed after {max_retries} attempts. "
                        f"Last error: {e}"
                    ) from e

    def _extract_image_from_response(self, response) -> Image.Image | None:
        """
        Extract a PIL Image from a Gemini API response.
        Handles different response formats across SDK versions.
        """
        # Try candidates (the standard response structure)
        if hasattr(response, "candidates") and response.candidates:
            for candidate in response.candidates:
                if hasattr(candidate, "content") and candidate.content:  # noqa: SIM102 — nested guards kept for readability
                    if hasattr(candidate.content, "parts") and candidate.content.parts:
                        for part in candidate.content.parts:
                            # Check for inline_data (image bytes)
                            if hasattr(part, "inline_data") and part.inline_data:  # noqa: SIM102 — nested guards kept for readability
                                if hasattr(part.inline_data, "data") and part.inline_data.data:
                                    img_data = part.inline_data.data
                                    if isinstance(img_data, bytes):
                                        return Image.open(BytesIO(img_data)).convert("RGB")
                                    elif isinstance(img_data, str):
                                        # Might be base64 encoded
                                        return Image.open(BytesIO(base64.b64decode(img_data))).convert("RGB")

        # Try the response.text or response.parts directly
        if hasattr(response, "parts") and response.parts:
            for part in response.parts:
                if hasattr(part, "inline_data") and part.inline_data:  # noqa: SIM102 — nested guards kept for readability
                    if hasattr(part.inline_data, "data") and part.inline_data.data:
                        img_data = part.inline_data.data
                        if isinstance(img_data, bytes):
                            return Image.open(BytesIO(img_data)).convert("RGB")

        logger.warning("Could not extract image from Gemini response")
        logger.debug(f"Response structure: {response}")
        return None

    def _image_to_bytes(self, img: Image.Image, format: str = "JPEG") -> bytes:
        """Convert a PIL Image to bytes for API transmission."""
        buf = BytesIO()
        # Ensure RGB for JPEG
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(buf, format=format, quality=95)
        return buf.getvalue()

    def check_fidelity(
        self,
        original_path: str,
        edited_path: str,
    ) -> dict:
        """
        Compare original and edited images to detect potential fidelity issues.
        This is a basic heuristic check — not a full fidelity verification.

        Checks:
        - Image dimensions changed significantly
        - Colour distribution shifted dramatically

        Returns:
            Dict with 'passed' (bool) and 'issues' (list of strings)
        """
        issues = []
        original = Image.open(original_path).convert("RGB")
        edited = Image.open(edited_path).convert("RGB")

        # Check dimension changes
        orig_w, orig_h = original.size
        edit_w, edit_h = edited.size
        w_change = abs(edit_w - orig_w) / orig_w if orig_w else 0
        h_change = abs(edit_h - orig_h) / orig_h if orig_h else 0
        if w_change > 0.2 or h_change > 0.2:
            issues.append(f"Dimensions changed significantly: {orig_w}x{orig_h} → {edit_w}x{edit_h}")

        # Check average colour shift
        import statistics
        orig_pixels = list(original.resize((100, 100)).getdata())
        edit_pixels = list(edited.resize((100, 100)).getdata())

        orig_avg_r = statistics.mean(p[0] for p in orig_pixels)
        orig_avg_g = statistics.mean(p[1] for p in orig_pixels)
        orig_avg_b = statistics.mean(p[2] for p in orig_pixels)
        edit_avg_r = statistics.mean(p[0] for p in edit_pixels)
        edit_avg_g = statistics.mean(p[1] for p in edit_pixels)
        edit_avg_b = statistics.mean(p[2] for p in edit_pixels)

        colour_shift = (
            abs(edit_avg_r - orig_avg_r) +
            abs(edit_avg_g - orig_avg_g) +
            abs(edit_avg_b - orig_avg_b)
        ) / 3
        if colour_shift > 40:  # Significant average colour shift
            issues.append(f"Significant colour shift detected: avg shift = {colour_shift:.1f}")

        return {
            "passed": len(issues) == 0,
            "issues": issues,
        }