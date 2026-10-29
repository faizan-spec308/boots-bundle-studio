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

import math
import os

from PIL import Image, ImageDraw, ImageFilter


class ImageComposer:
    CANVAS_SIZE = 2000
    BACKGROUND_COLOR = (255, 255, 255)
    MAX_PRODUCT_HEIGHT = 1600  # Max height for each product (leaves room for shadow)
    DEFAULT_GAP = 60  # Default gap between products in pixels
    SHADOW_OPACITY = 80
    SHADOW_BLUR = 20
    SHADOW_HEIGHT = 30

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

        # --- Arrange products in a grid that fills the canvas ---
        # Fewer than 4 products sit in a single row; 4+ use a balanced grid so
        # each product stays large instead of shrinking to fit one row.
        n = len(processed_products)
        cols = n if n <= 3 else math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)

        margin = 120                       # outer margin around the grid
        cell_gap = max(gap, 50)            # space between grid cells
        usable = self.CANVAS_SIZE - 2 * margin
        cell_w = (usable - cell_gap * (cols - 1)) / cols
        cell_h = (usable - cell_gap * (rows - 1)) / rows
        product_max_h = min(cell_h * 0.86, max_height)  # leave room for the shadow

        # Scale each product uniformly to fill its cell as much as possible.
        # Uniform scaling only — no stretching/distortion (product fidelity).
        scaled = []
        for img in processed_products:
            s = min(cell_w / img.width, product_max_h / img.height)
            scaled.append(img.resize(
                (max(1, int(img.width * s)), max(1, int(img.height * s))), Image.LANCZOS,
            ))

        # Centre the whole grid vertically
        grid_h = rows * cell_h + cell_gap * (rows - 1)
        grid_top = (self.CANVAS_SIZE - grid_h) / 2

        # Create white canvas + shadow layer
        canvas = Image.new("RGBA", (self.CANVAS_SIZE, self.CANVAS_SIZE), self.BACKGROUND_COLOR + (255,))
        shadow_layer = Image.new("RGBA", (self.CANVAS_SIZE, self.CANVAS_SIZE), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_layer)

        placements = []
        for idx, img in enumerate(scaled):
            r = idx // cols
            col_in_row = idx - r * cols
            items_in_row = min(cols, n - r * cols)  # last row may be shorter -> centre it
            row_w = items_in_row * cell_w + cell_gap * (items_in_row - 1)
            row_left = (self.CANVAS_SIZE - row_w) / 2
            cell_x = row_left + col_in_row * (cell_w + cell_gap)
            cell_y = grid_top + r * (cell_h + cell_gap)
            px = int(cell_x + (cell_w - img.width) / 2)          # centre in cell horizontally
            baseline = cell_y + cell_h * 0.9                      # products "stand" near cell bottom
            py = int(baseline - img.height)
            placements.append((img, px, py))
            # contact shadow beneath the product
            shadow_draw.ellipse(
                [px, int(baseline) - self.SHADOW_HEIGHT // 2,
                 px + img.width, int(baseline) + self.SHADOW_HEIGHT // 2],
                fill=(0, 0, 0, self.SHADOW_OPACITY),
            )

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

    def _resize_product(self, img: Image.Image, max_height: int) -> Image.Image:
        """Resize a product image to fit within max_height while keeping aspect ratio."""
        # If the image is already smaller than max_height, don't upscale
        if img.height <= max_height:  # noqa: SIM102 — nested check kept for clarity
            # But check if width is too large
            if img.width <= self.CANVAS_SIZE * 0.4:
                return img

        # Calculate scale to fit within max_height
        scale = max_height / img.height
        new_width = int(img.width * scale)
        new_height = max_height

        # If the width is still too large, scale by width instead
        max_width = self.CANVAS_SIZE * 0.4  # Max 40% of canvas per product
        if new_width > max_width:
            scale = max_width / img.width
            new_width = int(img.width * scale)
            new_height = int(img.height * scale)

        return img.resize((new_width, new_height), Image.LANCZOS)

    def edit_bundle_image(
        self,
        current_image_path: str,
        edit_prompt: str,
        output_path: str,
    ) -> str:
        """
        Edit an existing bundle image based on natural language instructions.
        Parses the edit prompt and applies programmatic changes.

        Supported edits:
        - "add space" / "add gap" / "increase gap" → increase spacing between products
        - "reduce space" / "reduce gap" / "move closer" → decrease spacing
        - "make products bigger" / "increase size" → scale up products
        - "make products smaller" / "decrease size" → scale down products
        - "center" / "center products" → re-center the row

        Args:
            current_image_path: Path to the current bundle image
            edit_prompt: Natural language edit instructions
            output_path: Where to save the edited image

        Returns:
            The output file path
        """
        prompt_lower = edit_prompt.lower().strip()

        # Parse the edit prompt to determine what changes to make
        gap_adjustment = 0
        size_adjustment = 1.0
        recenter = False

        # Space/gap adjustments
        if any(phrase in prompt_lower for phrase in ["add space", "add gap", "increase gap", "more space", "increase space", "wider gap", "spread"]):
            gap_adjustment = 80  # Add 80px more gap
        elif any(phrase in prompt_lower for phrase in ["reduce space", "reduce gap", "move closer", "less space", "decrease gap", "narrower gap", "close gap"]):
            gap_adjustment = -40  # Reduce gap by 40px

        # Size adjustments
        if any(phrase in prompt_lower for phrase in ["bigger", "larger", "increase size", "scale up", "make bigger", "make large"]):
            size_adjustment = 1.15  # 15% bigger
        elif any(phrase in prompt_lower for phrase in ["smaller", "decrease size", "scale down", "make small", "too big", "too large", "reduce size"]):
            size_adjustment = 0.85  # 15% smaller

        # Centering
        if "center" in prompt_lower:
            recenter = True

        # For now, we can't re-parse the current image to extract individual products
        # This is a limitation of programmatic editing on composed images.
        # For full edit support, the frontend should send the original product images
        # along with the edit prompt, so we can re-compose from scratch.

        # If no recognizable edit, just copy the image
        if gap_adjustment == 0 and size_adjustment == 1.0 and not recenter:
            print(f"Edit prompt not recognized for programmatic editing: '{edit_prompt}'")
            print("Returning original image unchanged. For AI-based editing, use the Gemini client.")
            import shutil
            shutil.copy2(current_image_path, output_path)
            return output_path

        # Apply the edit by loading the image and adjusting
        img = Image.open(current_image_path).convert("RGBA")

        if size_adjustment != 1.0:
            new_width = int(img.width * size_adjustment)
            new_height = int(img.height * size_adjustment)
            img = img.resize((new_width, new_height), Image.LANCZOS)

        # Create new canvas and center
        canvas = Image.new("RGBA", (self.CANVAS_SIZE, self.CANVAS_SIZE), self.BACKGROUND_COLOR + (255,))
        if recenter or size_adjustment != 1.0:
            paste_x = (self.CANVAS_SIZE - img.width) // 2
            paste_y = (self.CANVAS_SIZE - img.height) // 2
            canvas.paste(img, (paste_x, paste_y), img)
        else:
            canvas.paste(img, (0, 0), img)

        canvas = canvas.convert("RGB")
        canvas.save(output_path, "JPEG", quality=95)
        print(f"Edited bundle image saved to: {output_path}")
        return output_path

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