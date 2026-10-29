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
    ) -> str:
        """
        Compose a bundle image from individual product photos.

        Args:
            product_images: List of file paths to individual product images
            output_path: Where to save the composed image
            quantities: List of quantities for each product (e.g. [3, 1] = 3 of product A, 1 of product B)
            gap: Gap between products in pixels (default: 60)
            max_height: Max height for products in pixels (default: 1600)

        Returns:
            The output file path
        """
        if gap is None:
            gap = self.DEFAULT_GAP
        if max_height is None:
            max_height = self.MAX_PRODUCT_HEIGHT

        # Expand product images based on quantities
        expanded_images = []
        if quantities:
            for img_path, qty in zip(product_images, quantities):
                for _ in range(qty):
                    expanded_images.append(img_path)
        else:
            expanded_images = product_images.copy()

        # Check if we need the roundel (6+ identical items)
        use_roundel = False
        if len(expanded_images) >= 6 and len(set(expanded_images)) == 1:
            use_roundel = True
            expanded_images = [expanded_images[0]]  # Just use one image

        # Load and process all product images
        processed_products = []
        for img_path in expanded_images:
            if not os.path.exists(img_path):
                print(f"WARNING: Product image not found: {img_path}")
                continue
            img = Image.open(img_path).convert("RGBA")
            processed_products.append(img)

        if not processed_products:
            raise ValueError("No valid product images found")

        # Trim surrounding whitespace so each product fills its frame, then scale
        # every product to a common target height (~75% of the canvas) so products
        # stay large instead of tiny in a sea of white. Fidelity is preserved:
        # uniform scaling only, exact product pixels — just the white margins removed.
        trimmed = [self._trim_whitespace(img) for img in processed_products]
        target_height = min(int(self.CANVAS_SIZE * 0.75), max_height)  # ~1500px
        resized_products = [self._resize_product(img, target_height) for img in trimmed]

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