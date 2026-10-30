"""
Boots Bundle Image Studio — Image Composer
==========================================
Programmatic image compositing using PIL/Pillow.
Places actual product photos on a 2000x2000 white canvas with precise
pixel control — zero AI generation, 100% product fidelity, instant speed.

This replaces the AI generate_image approach which was slow (30 min) and
altered product colours, artwork, text, and proportions.
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFilter


class ImageComposer:
    CANVAS_SIZE = 2000
    BACKGROUND_COLOR = (255, 255, 255)
    MAX_PRODUCT_HEIGHT = 1500  # 75% of canvas — products fill the canvas, not tiny
    DEFAULT_GAP = 60  # Default gap between products in pixels
    SHADOW_OPACITY = 120
    SHADOW_BLUR = 25
    SHADOW_HEIGHT = 40

    def __init__(self, roundel_path: str | None = None):
        self.roundel_path = roundel_path

    def compose_bundle_image(
        self,
        product_images: list[str],
        output_path: str,
        quantities: list[int] | None = None,
        gap: int | None = None,
        max_height: int | None = None,
        relative_heights: list[float] | None = None,
    ) -> str:
        """
        Compose a bundle image from individual product photos.

        Args:
            product_images: List of file paths to individual product images
            output_path: Where to save the composed image
            quantities: List of quantities for each product (e.g. [3, 1] = 3 of product A, 1 of product B)
            gap: Gap between products in pixels (default: 60)
            max_height: Max height for products in pixels (default: 1600)
            relative_heights: Optional per-product relative heights (aligned with
                product_images), e.g. [1.0, 0.79, 0.53], so the composed products
                keep the real-world size differences measured from the original
                bundle image. When omitted, all products are scaled to one height
                (correct for identical multipack units).

        Returns:
            The output file path
        """
        if gap is None:
            gap = self.DEFAULT_GAP
        if max_height is None:
            max_height = self.MAX_PRODUCT_HEIGHT

        # Expand product images (and their relative heights) based on quantities
        expanded_images = []
        expanded_rel: list[float] = []
        if quantities:
            for i, (img_path, qty) in enumerate(zip(product_images, quantities)):
                rel = relative_heights[i] if relative_heights else 1.0
                for _ in range(qty):
                    expanded_images.append(img_path)
                    expanded_rel.append(rel)
        else:
            expanded_images = product_images.copy()
            expanded_rel = list(relative_heights) if relative_heights else [1.0] * len(expanded_images)

        # Check if we need the roundel (6+ identical items)
        use_roundel = False
        if len(expanded_images) >= 6 and len(set(expanded_images)) == 1:
            use_roundel = True
            expanded_images = [expanded_images[0]]  # Just use one image
            expanded_rel = [1.0]

        # Load and process all product images (keeping each image's relative height)
        processed_products = []
        processed_rel = []
        for img_path, rel in zip(expanded_images, expanded_rel):
            if not os.path.exists(img_path):
                print(f"WARNING: Product image not found: {img_path}")
                continue
            img = Image.open(img_path).convert("RGBA")
            processed_products.append(img)
            processed_rel.append(rel)

        if not processed_products:
            raise ValueError("No valid product images found")

        # Trim surrounding whitespace so each product fills its frame, then scale.
        # The tallest product reaches the target height (~75% of the canvas); the
        # others are scaled by their relative height so real-world size differences
        # measured from the original are preserved. Fidelity is kept: uniform
        # per-product scaling, exact product pixels — only white margins removed.
        trimmed = [self._trim_whitespace(img) for img in processed_products]
        target_height = min(int(self.CANVAS_SIZE * 0.75), max_height)  # ~1500px
        max_rel = max(processed_rel) or 1.0
        resized_products = [
            self._resize_product(img, max(40, int(target_height * (rel / max_rel))))
            for img, rel in zip(trimmed, processed_rel)
        ]

        # Single horizontal row (shelf layout). If the row is wider than the canvas,
        # scale all products down proportionally so they still fit with padding.
        total_width = sum(i.width for i in resized_products) + gap * (len(resized_products) - 1)
        max_total_width = self.CANVAS_SIZE - 200  # 100px padding each side
        if total_width > max_total_width:
            scale = max_total_width / total_width
            resized_products = [
                i.resize((max(1, int(i.width * scale)), max(1, int(i.height * scale))), Image.LANCZOS)
                for i in resized_products
            ]
            total_width = sum(i.width for i in resized_products) + gap * (len(resized_products) - 1)

        # Centre the row horizontally, and vertically on a shared baseline.
        start_x = (self.CANVAS_SIZE - total_width) // 2
        max_h = max(i.height for i in resized_products)
        baseline = self.CANVAS_SIZE // 2 + max_h // 2

        # Create white canvas + shadow layer
        canvas = Image.new("RGBA", (self.CANVAS_SIZE, self.CANVAS_SIZE), self.BACKGROUND_COLOR + (255,))
        shadow_layer = Image.new("RGBA", (self.CANVAS_SIZE, self.CANVAS_SIZE), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_layer)

        placements = []
        current_x = start_x
        for img in resized_products:
            placements.append((img, current_x, baseline - img.height))
            # contact shadow: an ellipse 20% wider than the product, centred under it
            shadow_w = int(img.width * 1.2)
            shadow_x = current_x - (shadow_w - img.width) // 2
            shadow_draw.ellipse(
                [shadow_x, baseline - self.SHADOW_HEIGHT // 2,
                 shadow_x + shadow_w, baseline + self.SHADOW_HEIGHT // 2],
                fill=(0, 0, 0, self.SHADOW_OPACITY),
            )
            current_x += img.width + gap

        # Blur the shadow layer, then paste products on top
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=self.SHADOW_BLUR))
        canvas = Image.alpha_composite(canvas, shadow_layer)
        for img, px, py in placements:
            canvas.paste(img, (px, py), img)  # alpha channel as mask

        # Apply roundel if needed (6+ identical items)
        if use_roundel and self.roundel_path and os.path.exists(self.roundel_path):
            roundel = Image.open(self.roundel_path).convert("RGBA")
            # Scale roundel to ~15% of canvas size
            roundel_size = int(self.CANVAS_SIZE * 0.15)
            roundel = roundel.resize((roundel_size, roundel_size), Image.LANCZOS)
            # Position in top-right corner with some padding
            roundel_x = self.CANVAS_SIZE - roundel_size - 80
            roundel_y = 80
            canvas.paste(roundel, (roundel_x, roundel_y), roundel)

        # Convert to RGB (remove alpha) for JPEG
        canvas = canvas.convert("RGB")

        # Save
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        canvas.save(output_path, "JPEG", quality=95)
        print(f"Composed bundle image saved to: {output_path}")
        return output_path

    # Minimum template-match confidence to trust the measured relative sizes.
    # Below this, the component photo couldn't be located confidently in the
    # original (different angle, occlusion, heavy overlap) — caller should route
    # the bundle to Manual Review rather than compose at a guessed size.
    MATCH_MIN_SCORE = 0.60

    def measure_relative_heights(
        self, original_path: str, product_images: list[str],
    ) -> tuple[list[float] | None, float, list[int] | None]:
        """Find each product's real height AND horizontal position in the
        original bundle image via multi-scale template matching, so a rebuild can
        preserve both the size differences (a small dropper stays smaller than a
        tall bottle) and the left-to-right order products appear in.

        Returns (relative_heights, min_score, x_positions). relative_heights is
        normalised so the tallest product is 1.0, aligned with product_images;
        x_positions is each product's matched left-edge x (same order). If
        anything can't be measured or confidence is low, returns (None, score,
        None) and the caller should fall back to Manual Review.
        """
        try:
            import cv2
            import numpy as np
        except ImportError:
            return None, 0.0, None
        if not original_path or not os.path.exists(original_path) or not product_images:
            return None, 0.0, None

        def _to_cv(pil_img, max_dim):
            img = self._trim_whitespace(pil_img.convert("RGBA")).convert("RGB")
            scale = min(1.0, max_dim / max(img.width, img.height))
            if scale < 1.0:
                img = img.resize((max(1, int(img.width * scale)),
                                  max(1, int(img.height * scale))), Image.LANCZOS)
            return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

        try:
            orig = _to_cv(Image.open(original_path), 500)
        except OSError:
            return None, 0.0, None
        oh, ow = orig.shape[:2]

        heights: list[float] = []
        xs: list[int] = []
        min_score = 1.0
        for path in product_images:
            if not path or not os.path.exists(path):
                return None, 0.0, None
            try:
                tmpl = _to_cv(Image.open(path), 500)
            except OSError:
                return None, 0.0, None
            best_score, best_h, best_x = -1.0, None, 0
            th0 = tmpl.shape[0]
            # Try the product at a range of heights relative to the original.
            for pct in range(20, 100, 5):
                target_h = int(oh * pct / 100)
                scale = target_h / th0
                tw = int(tmpl.shape[1] * scale)
                if target_h < 15 or target_h > oh or tw < 8 or tw > ow:
                    continue
                resized = cv2.resize(tmpl, (tw, target_h), interpolation=cv2.INTER_AREA)
                res = cv2.matchTemplate(orig, resized, cv2.TM_CCOEFF_NORMED)
                _, maxv, _, maxloc = cv2.minMaxLoc(res)
                if maxv > best_score:
                    best_score, best_h, best_x = maxv, target_h, int(maxloc[0])
            if best_h is None:
                return None, 0.0, None
            heights.append(best_h)
            xs.append(best_x)
            min_score = min(min_score, best_score)

        if min_score < self.MATCH_MIN_SCORE:
            return None, min_score, None
        tallest = max(heights) or 1
        return [round(h / tallest, 3) for h in heights], min_score, xs

    def _resize_product(self, img: Image.Image, target_height: int) -> Image.Image:
        """Scale a product to the target height, keeping aspect ratio. Always
        scales (including UP) so products fill the canvas rather than staying at
        their small download size."""
        scale = target_height / img.height
        new_width = max(1, int(img.width * scale))
        return img.resize((new_width, target_height), Image.LANCZOS)

    def _trim_whitespace(self, img: Image.Image) -> Image.Image:
        """Crop the near-white margins around a product so it fills its frame.
        Only surrounding white background is removed — the product pixels are
        untouched (fidelity preserved)."""
        gray = img.convert("RGB").convert("L")
        # Content = pixels darker than near-white; getbbox returns their bounds.
        mask = gray.point(lambda v: 255 if v < 250 else 0)
        bbox = mask.getbbox()
        if not bbox:
            return img
        pad = 8  # small safety margin so product edges are never clipped
        left = max(0, bbox[0] - pad)
        top = max(0, bbox[1] - pad)
        right = min(img.width, bbox[2] + pad)
        bottom = min(img.height, bbox[3] + pad)
        return img.crop((left, top, right, bottom))

    def compose_from_product_images(
        self,
        product_image_paths: list[str],
        quantities: list[int],
        output_path: str,
        gap: int | None = None,
    ) -> str:
        """
        Compose a bundle image from individual product photos with quantities.
        This is the primary method for initial generation.

        Args:
            product_image_paths: List of file paths to individual product images
            quantities: List of quantities for each product
            output_path: Where to save the composed image
            gap: Gap between products in pixels

        Returns:
            The output file path
        """
        return self.compose_bundle_image(
            product_images=product_image_paths,
            output_path=output_path,
            quantities=quantities,
            gap=gap,
        )