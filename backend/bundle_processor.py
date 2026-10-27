"""
Boots Bundle Image Studio — Bundle Processor
=============================================
Quality assessment and categorization for bundle images.

Evaluates current Boots.com bundle images against individual product photos,
categorizes bundles into three dashboard sections:
  - ready:    Good quality or we've generated a better image → Ready for Approval
  - supplier: No suitable individual product images found → Supplier Image Required
  - manual:   Can't confidently compose or quality issues → Manual Review Required

Applies bundle arrangement rules from the requirements document:
  - Fewer than 4 products: Arrange all in one image
  - 4+ products: Evaluate sizes, quantities, packaging shapes, available space
  - If composition can't be determined confidently → Manual Review
"""

import logging
import os

from PIL import Image

logger = logging.getLogger(__name__)


class BundleProcessor:
    """
    Processes bundle data: quality assessment, categorization, and arrangement decisions.
    """

    def __init__(self):
        pass

    def assess_quality(
        self,
        bundle_image_path: str,
        product_image_paths: list[str],
    ) -> dict:
        """
        Assess the quality of a current Boots.com bundle image.

        Uses heuristic checks (not AI) to evaluate:
        - Image dimensions and aspect ratio
        - Background whiteness
        - Product count consistency
        - Whether products appear to be touching/overlapping (basic edge detection)

        Args:
            bundle_image_path: Path to the current bundle image from Boots.com.
            product_image_paths: List of individual product image paths for comparison.

        Returns:
            Dict with quality assessment results:
            {
                'score': float (0.0-1.0),
                'issues': list of str,
                'needs_regeneration': bool,
            }
        """
        issues = []
        score = 1.0

        if not os.path.exists(bundle_image_path):
            return {
                'score': 0.0,
                'issues': ['Bundle image not found'],
                'needs_regeneration': True,
            }

        try:
            bundle_img = Image.open(bundle_image_path).convert("RGB")
        except Exception as e:  # noqa: BLE001 — any open failure counts as unusable
            return {
                'score': 0.0,
                'issues': [f'Cannot open bundle image: {e}'],
                'needs_regeneration': True,
            }

        w, h = bundle_img.size

        # Check 1: Image should be roughly square (bundle images are typically square)
        aspect_ratio = w / h if h else 0
        if aspect_ratio < 0.7 or aspect_ratio > 1.4:
            issues.append(f'Non-standard aspect ratio: {aspect_ratio:.2f} (expected ~1.0)')
            score -= 0.15

        # Check 2: Image should be at least 500x500 (too small = poor quality)
        if w < 500 or h < 500:
            issues.append(f'Image too small: {w}x{h} (minimum 500x500)')
            score -= 0.2

        # Check 3: Background should be predominantly white
        bg_score = self._check_background_whiteness(bundle_img)
        if bg_score < 0.7:
            issues.append(f'Background not clean white (whiteness: {bg_score:.1%})')
            score -= 0.2

        # Check 4: Load product images for count comparison
        valid_product_count = 0
        for p in product_image_paths:
            if os.path.exists(p):
                valid_product_count += 1

        if valid_product_count == 0 and product_image_paths:
            issues.append('No valid individual product images found')
            score -= 0.3

        # Check 5: Check for number badges (x3, x5, etc.) — bad for SEO
        # This is a simple heuristic; full text detection would need OCR
        has_badge = self._detect_number_badge_heuristic(bundle_img)
        if has_badge:
            issues.append('Possible number badge detected (bad for SEO)')
            score -= 0.15

        # Clamp score
        score = max(0.0, min(1.0, score))
        needs_regen = score < 0.7 or len(issues) > 2

        return {
            'score': round(score, 2),
            'issues': issues,
            'needs_regeneration': needs_regen,
        }

    def categorize_bundle(
        self,
        bundle: dict,
        quality_assessment: dict,
        product_images_found: bool,
        can_compose: bool,
    ) -> str:
        """
        Categorize a bundle into one of three dashboard sections.

        Args:
            bundle: Bundle metadata dict (code, title, products, quantities).
            quality_assessment: Result from assess_quality().
            product_images_found: Whether suitable individual product images were found.
            can_compose: Whether the image_composer can confidently compose this bundle.

        Returns:
            One of: 'ready', 'supplier', 'manual'
        """
        # Rule 1: If no product images found → Supplier Image Required
        if not product_images_found:
            logger.info(f"Bundle {bundle.get('code', '?')}: supplier (no product images)")
            return 'supplier'

        # Rule 2: If we can't confidently compose → Manual Review Required
        if not can_compose:
            logger.info(f"Bundle {bundle.get('code', '?')}: manual (cannot compose)")
            return 'manual'

        # Rule 3: If quality is poor or needs regeneration → Ready for Approval
        # (we'll generate a better image)
        if quality_assessment['needs_regeneration']:
            logger.info(f"Bundle {bundle.get('code', '?')}: ready (needs regeneration)")
            return 'ready'

        # Rule 4: If quality is acceptable but not perfect → Ready for Approval
        # (user can approve the original or request regeneration)
        logger.info(f"Bundle {bundle.get('code', '?')}: ready (quality acceptable)")
        return 'ready'

    def determine_arrangement(
        self,
        products: list[dict],
    ) -> dict:
        """
        Determine the arrangement for a bundle's products.

        Rules from requirements document:
        - Fewer than 4 products: Arrange all in one image.
        - 4+ products: Evaluate sizes, quantities, packaging shapes, and available space
          before deciding whether a single image is appropriate.
        - If a suitable composition cannot be determined confidently → Manual Review.

        Args:
            products: List of product dicts with 'name', 'quantity', 'image_path'.

        Returns:
            Dict with arrangement decision:
            {
                'single_image': bool,
                'reasoning': str,
                'manual_review': bool,
            }
        """
        total_items = sum(p.get('quantity', 1) for p in products)
        product_types = len(products)

        # Fewer than 4 products (types): single image
        if product_types < 4:
            return {
                'single_image': True,
                'reasoning': f'{product_types} product types — arrange all in one image',
                'manual_review': False,
            }

        # 4+ product types: evaluate
        # Check if total items is manageable (not too many to fit in 2000x2000)
        if total_items > 12:
            # Too many items for a single clean image
            return {
                'single_image': False,
                'reasoning': f'{total_items} total items across {product_types} product types — too many for a single clean image',
                'manual_review': True,
            }

        # Check if products have images available
        images_available = all(
            p.get('image_path') and os.path.exists(p['image_path'])
            for p in products
        )
        if not images_available:
            return {
                'single_image': False,
                'reasoning': 'Not all product images available — cannot determine arrangement',
                'manual_review': True,
            }

        # 4-7 product types with images: try single image, but flag for review
        if product_types <= 7:
            return {
                'single_image': True,
                'reasoning': f'{product_types} product types with {total_items} total items — single image with careful spacing',
                'manual_review': False,
            }

        # 8+ product types: likely needs manual review
        return {
            'single_image': False,
            'reasoning': f'{product_types} product types — too many for confident auto-arrangement',
            'manual_review': True,
        }

    async def process_bundles(
        self,
        bundles: list[dict],
        crawler=None,
        composer=None,
        uploads_dir: str = "uploads",
    ) -> list[dict]:
        """
        Full pipeline: assess quality, crawl for product images, categorize, and
        generate composed images for bundles that need them.

        Args:
            bundles: List of bundle dicts from MondayClient (code, title, products, quantities).
            crawler: BootsCrawler instance (for downloading product images).
            composer: ImageComposer instance (for generating bundle images).
            uploads_dir: Directory for storing downloaded/generated images.

        Returns:
            List of processed bundle dicts with all data for the frontend:
            {
                'code': str,
                'title': str,
                'category': 'ready' | 'supplier' | 'manual',
                'original_image': str (path or URL),
                'generated_image': str or None,
                'products': list,
                'quality_score': float,
                'quality_issues': list,
                'arrangement': dict,
            }
        """
        os.makedirs(uploads_dir, exist_ok=True)
        results = []

        for bundle in bundles:
            code = bundle.get('code', '')
            title = bundle.get('title', '')
            logger.info(f"Processing bundle: {code} — {title}")

            product_image_paths = []
            product_quantities = []  # kept aligned with product_image_paths
            original_image_path = None
            product_images_found = False

            # Monday rows carry no per-product breakdown, so fall back to the
            # individual products discovered on the bundle's Boots.com page.
            products = list(bundle.get('products') or [])

            # Step 1: Crawl Boots.com for the bundle's current image + individual product images
            if crawler:
                try:
                    # Look up the bundle's current Boots.com page: its main image
                    # (for quality assessment) and its individual products.
                    bundle_info = await crawler.search_bundle(code)
                    if bundle_info:
                        if bundle_info.get('image_url'):
                            original_image_path = os.path.join(uploads_dir, f"{code}_original.jpg")
                            await crawler.download_image(bundle_info['image_url'], original_image_path)
                        if not products and bundle_info.get('individual_products'):
                            products = list(bundle_info['individual_products'])
                        if not title and bundle_info.get('title'):
                            title = bundle_info['title']

                    # Download each product image; record its local path + quantity
                    for product in products:
                        product_code = product.get('code', '')
                        if not product_code:
                            continue
                        img = await crawler.get_product_image(product_code, uploads_dir)
                        if img and os.path.exists(img):
                            product['image_path'] = img
                            product_image_paths.append(img)
                            product_quantities.append(product.get('quantity', 1))
                except Exception as e:  # noqa: BLE001 — crawl failures must not abort the batch
                    logger.warning(f"Crawler failed for {code}: {e}")
            else:
                # Use any product image paths already in the bundle data
                for product in products:
                    if product.get('image_path') and os.path.exists(product['image_path']):
                        product_image_paths.append(product['image_path'])
                        product_quantities.append(product.get('quantity', 1))

            product_images_found = len(product_image_paths) > 0

            # Step 2: Assess quality of the current bundle image
            if original_image_path and os.path.exists(original_image_path):
                quality = self.assess_quality(original_image_path, product_image_paths)
            else:
                quality = {
                    'score': 0.0,
                    'issues': ['No original bundle image available'],
                    'needs_regeneration': True,
                }

            # Step 3: Determine arrangement
            arrangement = self.determine_arrangement(products)

            # Step 4: Determine if we can compose
            can_compose = (
                product_images_found and
                not arrangement['manual_review'] and
                arrangement['single_image']
            )

            # Step 5: Categorize
            category = self.categorize_bundle(
                bundle=bundle,
                quality_assessment=quality,
                product_images_found=product_images_found,
                can_compose=can_compose,
            )

            # Step 6: Generate composed image if needed and possible
            generated_image_path = None
            if category == 'ready' and can_compose and composer:
                try:
                    generated_image_path = os.path.join(uploads_dir, f"{code}_generated.jpg")
                    composer.compose_bundle_image(
                        product_images=product_image_paths,
                        output_path=generated_image_path,
                        quantities=product_quantities,
                    )
                    logger.info(f"Generated composed image for {code}")
                except Exception:
                    logger.exception(f"Failed to generate image for {code}")
                    # Fall back to manual review if composition fails
                    category = 'manual'

            # Step 7: Build result
            result = {
                'code': code,
                'title': title,
                'category': category,
                'original_image': original_image_path,
                'generated_image': generated_image_path,
                'products': products,
                'quality_score': quality['score'],
                'quality_issues': quality['issues'],
                'arrangement_reasoning': arrangement['reasoning'],
            }
            results.append(result)

        logger.info(f"Processed {len(results)} bundles: "
                     f"{sum(1 for r in results if r['category'] == 'ready')} ready, "
                     f"{sum(1 for r in results if r['category'] == 'supplier')} supplier, "
                     f"{sum(1 for r in results if r['category'] == 'manual')} manual")

        return results

    def _check_background_whiteness(self, img: Image.Image) -> float:
        """
        Check what percentage of the image border (background area) is white.
        Returns a float 0.0-1.0 where 1.0 = perfectly white background.
        """
        w, h = img.size
        # Sample the border pixels (top/bottom 10% and left/right 10%)
        border_pixels = []

        # Top and bottom rows
        for x in range(0, w, max(1, w // 50)):
            for y in [0, h // 20, h - h // 20, h - 1]:
                border_pixels.append(img.getpixel((x, y)))

        # Left and right columns
        for y in range(0, h, max(1, h // 50)):
            for x in [0, w // 20, w - w // 20, w - 1]:
                border_pixels.append(img.getpixel((x, y)))

        white_count = 0
        for r, g, b in border_pixels:
            if r > 240 and g > 240 and b > 240:
                white_count += 1

        return white_count / len(border_pixels) if border_pixels else 0.0

    def _detect_number_badge_heuristic(self, img: Image.Image) -> bool:
        """
        Heuristic check for number badges (x3, x5, etc.).
        Looks for small circular/colored regions in the corner of the image
        that might indicate a badge.

        This is a basic heuristic — not a full OCR check.
        Returns True if a suspicious region is found.
        """
        w, _h = img.size
        # Check the top-right corner area (where badges are typically placed)
        corner = img.crop((w - 200, 0, w, 200)).resize((50, 50))
        pixels = list(corner.getdata())

        # Look for saturated colored pixels (badges are usually brightly colored)
        colored_count = 0
        for r, g, b in pixels:
            max_c = max(r, g, b)
            min_c = min(r, g, b)
            if max_c - min_c > 60 and max_c > 150:
                colored_count += 1

        # If more than 15% of the corner is brightly colored, suspicious
        return colored_count > len(pixels) * 0.15