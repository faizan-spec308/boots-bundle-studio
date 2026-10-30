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

from PIL import Image, ImageChops


class ImageComposer:
    CANVAS_SIZE = 2000
    BACKGROUND_COLOR = (255, 255, 255)
    MAX_PRODUCT_HEIGHT = 1500  # 75% of canvas — products fill the canvas, not tiny
    DEFAULT_GAP = 60  # Default gap between products in pixels

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

        # Plain white canvas — products only, no added shadows or effects.
        canvas = Image.new("RGB", (self.CANVAS_SIZE, self.CANVAS_SIZE), self.BACKGROUND_COLOR)

        placements = []
        current_x = start_x
        for img in resized_products:
            placements.append((img, current_x, baseline - img.height))
            current_x += img.width + gap

        for img, px, py in placements:
            # Multiply-blend instead of pasting: a product photo's white background
            # merges seamlessly with the canvas (no white "box" edges where crops
            # meet), while every product pixel — white packaging included — stays
            # intact. Near-white background noise is snapped to pure white first
            # so it can't tint the canvas.
            flat = Image.new("RGB", img.size, self.BACKGROUND_COLOR)
            flat.paste(img, (0, 0), img if img.mode == "RGBA" else None)
            # (Only the last few levels — white packaging often has faint grey
            # edges around 240-250 that must survive.)
            flat = flat.point(lambda v: 255 if v >= 253 else v)
            box = (px, py, px + flat.width, py + flat.height)
            canvas.paste(ImageChops.multiply(canvas.crop(box), flat), box)

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

    def segment_original(self, original_path: str, n: int) -> list[Image.Image] | None:
        """Cut the ORIGINAL bundle image into `n` product crops (left-to-right).
        This keeps the EXACT products (right variant, colours, sizes, order) from
        the original instead of relying on component photos, which often don't
        match.

        Tries 2D separation first (each product as its own connected shape —
        works even when products sit side by side at different heights), then
        falls back to vertical cuts at clean column gaps. Returns trimmed RGBA
        crops, or None if the products can't be separated cleanly (they touch or
        overlap, or the image doesn't actually show `n` products).
        """
        try:
            import numpy as np  # noqa: F401 — availability check
        except ImportError:
            return None
        if n < 2 or not original_path or not os.path.exists(original_path):
            return None
        try:
            base = self._trim_whitespace(Image.open(original_path).convert("RGBA"))
        except OSError:
            return None
        rgb = base.convert("RGB")
        w, h = rgb.size
        if w < 40 or h < 40:
            return None
        crops = self._segment_by_shapes(rgb, n)
        if crops:
            return crops
        return self._segment_by_columns(rgb, n)

    def _segment_by_shapes(self, rgb: Image.Image, n: int) -> list[Image.Image] | None:
        """Find the products as separate connected shapes on the background."""
        import numpy as np

        w, h = rgb.size
        scale = min(1.0, 400 / max(w, h))
        sw, sh = max(1, int(w * scale)), max(1, int(h * scale))
        small = np.asarray(rgb.resize((sw, sh), Image.BILINEAR)).astype(int)
        border = np.concatenate([small[0], small[-1], small[:, 0], small[:, -1]])
        bg = np.median(border, axis=0)
        fg = np.abs(small - bg).max(axis=2) > 14
        # Close tiny breaks inside a product (thin lids, glare) with a dilation.
        for _ in range(2):
            grown = fg.copy()
            grown[1:] |= fg[:-1]
            grown[:-1] |= fg[1:]
            grown[:, 1:] |= fg[:, :-1]
            grown[:, :-1] |= fg[:, 1:]
            fg = grown

        labels = np.zeros((sh, sw), dtype=np.int32)
        comps: list[tuple[int, int, int, int, int, int]] = []  # id, size, x0, y0, x1, y1
        next_id = 0
        for sy in range(sh):
            for sx in range(sw):
                if not fg[sy, sx] or labels[sy, sx]:
                    continue
                next_id += 1
                stack = [(sy, sx)]
                labels[sy, sx] = next_id
                size, x0, y0, x1, y1 = 0, sx, sy, sx, sy
                while stack:
                    cy, cx = stack.pop()
                    size += 1
                    x0, x1 = min(x0, cx), max(x1, cx)
                    y0, y1 = min(y0, cy), max(y1, cy)
                    for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                        if 0 <= ny < sh and 0 <= nx < sw and fg[ny, nx] and not labels[ny, nx]:
                            labels[ny, nx] = next_id
                            stack.append((ny, nx))
                comps.append((next_id, size, x0, y0, x1, y1))

        total = sum(c[1] for c in comps) or 1
        big = [c for c in comps if c[1] >= 0.04 * total]
        if len(big) != n:
            return None

        # Small islands (e.g. a logo printed on a WHITE box, whose face looks like
        # background) belong to the nearest main product — attach them rather
        # than treating them as another product and painting them out.
        def gap_to(b, cx, cy):
            dx = max(b[2] - cx, 0, cx - b[4])
            dy = max(b[3] - cy, 0, cy - b[5])
            return dx * dx + dy * dy

        lut = np.zeros(next_id + 1, dtype=np.int32)
        for c in comps:
            if c in big:
                lut[c[0]] = c[0]
            else:
                cx, cy = (c[2] + c[4]) / 2, (c[3] + c[5]) / 2
                lut[c[0]] = min(big, key=lambda b, cx=cx, cy=cy: gap_to(b, cx, cy))[0]
        groups = lut[labels]

        boxes = []
        for b in big:
            ys, xs = np.nonzero(groups == b[0])
            boxes.append((int(xs.min()), b[0], int(ys.min()), int(xs.max()), int(ys.max())))
        boxes.sort()  # left-to-right

        crops: list[Image.Image] = []
        inv = 1 / scale
        pad = int(0.02 * max(w, h))  # room for faint packaging edges; trim tidies it
        for x0, gid, y0, x1, y1 in boxes:
            # Hide every OTHER product inside this product's box, then crop.
            others = (groups > 0) & (groups != gid)
            hide = Image.fromarray((others * 255).astype(np.uint8)).resize((w, h), Image.NEAREST)
            clean = rgb.copy()
            clean.paste((255, 255, 255), mask=hide)
            box = (max(0, int(x0 * inv) - pad), max(0, int(y0 * inv) - pad),
                   min(w, int((x1 + 1) * inv) + pad), min(h, int((y1 + 1) * inv) + pad))
            seg = self._trim_whitespace(clean.crop(box).convert("RGBA"))
            if seg.width < 20 or seg.height < 20:
                return None
            crops.append(seg)
        return crops

    def _segment_by_columns(self, rgb: Image.Image, n: int) -> list[Image.Image] | None:
        """Fallback: cut at clean vertical gaps between side-by-side products."""
        import numpy as np

        w, h = rgb.size

        gray = np.asarray(rgb.convert("L"))
        # Count non-white pixels per column -> where the products actually are.
        content = (gray < 244).sum(axis=0).astype(float)
        if content.max() <= 0:
            return None
        k = max(3, w // 80)
        prof = np.convolve(content, np.ones(k) / k, mode="same")

        # Find a clean gap near each expected boundary (equal-width zones).
        splits: list[int] = []
        for i in range(1, n):
            center = w * i / n
            half = int(w / (2 * n))
            lo, hi = max(1, int(center - half)), min(w - 1, int(center + half))
            if hi <= lo:
                return None
            x = lo + int(np.argmin(prof[lo:hi]))
            left = prof[max(0, x - half):x]
            right = prof[x:min(w, x + half)]
            shoulder = min(
                left.max() if left.size else 0.0,
                right.max() if right.size else 0.0,
            )
            # A real gap drops well below the product content on both sides.
            if shoulder <= 0 or prof[x] > 0.45 * shoulder:
                return None
            splits.append(x)

        bounds = [0, *splits, w]
        crops: list[Image.Image] = []
        for a, b in zip(bounds[:-1], bounds[1:]):  # noqa: RUF007 — pairwise needs py3.10
            if b - a < 15:
                return None
            seg = self._trim_whitespace(rgb.crop((a, 0, b, h)).convert("RGBA"))
            if seg.width < 20 or seg.height < 20:
                return None
            crops.append(seg)
        return crops

    def rebuild_by_splitting(self, original_path: str, n: int, output_path: str) -> bool:
        """Separate the products out of the original and re-space them cleanly,
        preserving their real sizes. Returns True on success, False if the
        original can't be split cleanly (caller should fall back)."""
        crops = self.segment_original(original_path, n)
        if not crops:
            return False
        heights = [c.height for c in crops]
        tallest = max(heights) or 1
        rel = [h / tallest for h in heights]
        segdir = os.path.join(os.path.dirname(output_path) or ".", "_segcrops")
        os.makedirs(segdir, exist_ok=True)
        base = os.path.splitext(os.path.basename(output_path))[0]
        paths = []
        for i, crop in enumerate(crops):
            p = os.path.join(segdir, f"{base}_{i}.png")
            crop.save(p)
            paths.append(p)
        self.compose_bundle_image(
            paths, output_path, quantities=[1] * len(paths), relative_heights=rel,
        )
        return True

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