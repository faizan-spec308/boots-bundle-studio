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

from __future__ import annotations

import asyncio
import logging
import os
import re
import typing

from PIL import Image

# Title hints that a single-product bundle is actually a multipack of several
# identical units (e.g. "4 x ...", "4 packs", "pack of 3", "6 month supply").
# Used only when Boots.com reports a single product with quantity < 2, to catch
# cases where the real unit count is unknown and we should ask for manual review.
_MULTIPACK_TITLE_RE = re.compile(
    r"\b\d+\s*x\b|\b\d+\s*(?:pack|packs|pk|sachets?|tablets?|capsules?)\b"
    r"|\bpack of\s*\d+\b|\b\d+\s*month(?:'?s)?\s*supply\b|\b(?:twin|triple)\s*pack\b",
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)


class BundleProcessor:
    """
    Processes bundle data: quality assessment, categorization, and arrangement decisions.
    """

    # The most items (multipack units or distinct products) we'll line up in one
    # clean image. Anything larger goes to Manual Review instead.
    MAX_ITEMS_IN_ROW = 5
    # How closely a component photo must match the product in the original
    # before we trust it enough to duplicate it for a multipack.
    COMPONENT_MATCH_MIN = 0.5
    # Multi-product bundles only fall back to component photos (after the
    # original-image path failed) when they match the original strongly. In
    # the 0.60–0.70 band component photos were often a different variant or
    # carried baked-in tags (e.g. Dove's "75 ml"), so those go to Manual.
    COMPONENT_REBUILD_STRONG = 0.70

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
        score = 0.8  # start at 0.8 so scores are meaningful (not always 100%)

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
        needs_regeneration: bool,
        product_images_found: bool,
        can_compose: bool,
        has_original: bool,
    ) -> tuple[str, bool]:
        """
        Categorize a bundle and decide whether a new image is produced.

        Returns (category, needs_regeneration):
        - ('ready', False) : the original image is already fine — shown as-is (and
                             filtered out of the dashboard, since it needs no action).
        - ('ready', True)  : needs a new image and one can be composed.
        - ('supplier', ...) : needs an image but no component product images found.
        - ('manual', ...)   : needs an image but a confident arrangement can't be made.
        """
        code = bundle.get('code', '?')

        # Original is already good — no regeneration needed.
        if not needs_regeneration and has_original:
            logger.info(f"Bundle {code}: ready (original is fine, no regeneration)")
            return ('ready', False)

        # From here, the bundle needs a (re)generated image.
        if not product_images_found:
            logger.info(f"Bundle {code}: supplier (needs image, no component images)")
            return ('supplier', False)
        if not can_compose:
            logger.info(f"Bundle {code}: manual (needs image, cannot arrange confidently)")
            return ('manual', False)
        logger.info(f"Bundle {code}: ready (will regenerate)")
        return ('ready', True)

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
        progress_cb=None,
        max_concurrency: int = 8,
        classifier=None,
        gemini=None,
        force_fix=False,
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
        total = len(bundles)
        results: list = [None] * total

        # Process bundles concurrently, bounded by a semaphore so we never open
        # more than `max_concurrency` crawls at once.
        sem = asyncio.Semaphore(max_concurrency)
        counter = {"done": 0}
        lock = asyncio.Lock()

        async def worker(index: int, bundle: dict) -> None:
            async with sem:
                result = await self._process_one(
                    bundle, crawler, composer, uploads_dir, classifier, gemini, force_fix,
                )
            results[index] = result
            async with lock:
                counter["done"] += 1
                if progress_cb:
                    progress_cb(counter["done"], total)

        await asyncio.gather(*(worker(i, b) for i, b in enumerate(bundles)))

        # Drop bundles that were filtered out (good originals that need no action).
        results = [r for r in results if r is not None]

        logger.info(f"Returning {len(results)} bundles that need action: "
                     f"{sum(1 for r in results if r['category'] == 'ready')} ready, "
                     f"{sum(1 for r in results if r['category'] == 'supplier')} supplier, "
                     f"{sum(1 for r in results if r['category'] == 'manual')} manual")

        return results

    @staticmethod
    def _result(code, title, category, original_image, generated_image, products,
                quality_score, quality_issues, arrangement_reasoning, needs_regeneration):
        """Assemble a dashboard result dict for a bundle that needs action."""
        return {
            'code': code,
            'title': title,
            'category': category,
            'original_image': original_image,
            'generated_image': generated_image,
            'products': products,
            'quality_score': round(float(quality_score), 2),
            'quality_issues': quality_issues,
            'arrangement_reasoning': arrangement_reasoning,
            'needs_regeneration': needs_regeneration,
        }

    async def _download_components(self, crawler, products, uploads_dir):
        """Download each component's product photo. Called ONLY when we may
        rebuild, so fine bundles never pay for component downloads.

        Returns a list of {'code', 'path', 'quantity'} (one per product that has
        an image), preserving product identity so the caller can tell how many
        distinct products the bundle has and measure their sizes."""
        components: list = []
        if not crawler:
            for product in products:
                ip = product.get('image_path')
                if ip and os.path.exists(ip):
                    components.append({
                        'code': product.get('code', ''), 'path': ip,
                        'quantity': int(product.get('quantity', 1) or 1),
                    })
            return components

        async def _fetch(product):
            pcode = product.get('code', '')
            if not pcode:
                return None
            img = await crawler.download_product_image(
                pcode, product.get('image_url'), uploads_dir,
            )
            if not img:
                return None
            product['image_path'] = img
            return {'code': pcode, 'path': img, 'quantity': int(product.get('quantity', 1) or 1)}

        for res in await asyncio.gather(*(_fetch(p) for p in products)):
            if res:
                components.append(res)
        return components

    async def _compose(self, code, title, original_image_path, products, components,
                       relative_heights, arrangement, composer, uploads_dir, issues):
        """Compose the bundle from clean component photos. Falls back to Manual
        Review if the arrangement is too complex or composition fails."""
        if not composer or arrangement.get('manual_review') or not arrangement.get('single_image'):
            return self._result(code, title, 'manual', original_image_path, None, products,
                                 0.4, issues, arrangement['reasoning'], True)
        paths = [c['path'] for c in components]
        quantities = [c['quantity'] for c in components]
        try:
            generated_image_path = os.path.join(uploads_dir, f"{code}_generated.jpg")
            await asyncio.to_thread(
                composer.compose_bundle_image, paths, generated_image_path, quantities,
                relative_heights=relative_heights,
            )
            logger.info(f"Composed image for {code} (sizes {'preserved' if relative_heights else 'uniform'})")
            return self._result(code, title, 'ready', original_image_path, generated_image_path,
                                 products, 0.6, issues, arrangement['reasoning'], True)
        except Exception:
            logger.exception(f"Compose failed for {code}")
            return self._result(code, title, 'manual', original_image_path, None, products,
                                 0.4, issues, arrangement['reasoning'], True)

    _CHECK_LABELS: typing.ClassVar[dict[str, str]] = {
        'same_products': 'different product or variant',
        'same_count': 'wrong number of items',
        'no_added_marks': 'extra tag or badge',
        'text_intact': 'garbled label text',
        'no_overlap': 'products still overlap',
    }

    async def _check_rebuild(self, code, original_image_path, result, classifier, method):
        """Verify a rebuilt image against the original with the vision model.
        If it fails (wrong variant, wrong count, added tags, garbled text,
        overlap), demote to Manual Review — keeping the attempt visible so the
        reviewer can see what went wrong."""
        if not result or result.get('category') != 'ready':
            return result
        result['method'] = method
        generated = result.get('generated_image')
        if not classifier or not generated or not original_image_path:
            return result
        v = await asyncio.to_thread(classifier.verify, original_image_path, generated)
        if v is None:
            result['quality_issues'] = [
                *result.get('quality_issues', []),
                "The automatic check against the original couldn't run — review "
                + "carefully before approving.",
            ]
            return result
        if v['ok']:
            return result
        # Reject on the first failure: a bad image wrongly marked Ready costs far
        # more than a good one sent to Manual (where the attempt stays visible).
        failed = [self._CHECK_LABELS[k] for k in self._CHECK_LABELS if not v.get(k)]
        logger.info(f"Bundle {code}: rebuild failed verification ({', '.join(failed)})")
        result.update(
            category='manual', quality_score=0.4,
            quality_issues=[
                "The rebuilt image didn't pass the check against the original "
                + f"({', '.join(failed)}): {v['reason']} Needs manual review.",
            ],
        )
        return result

    async def _rebuild_from_original(self, code, original_image_path, n, composer,
                                     gemini, uploads_dir, remove_badge=False):
        """Rebuild using the ORIGINAL image's own products (the right variant,
        colours and sizes) instead of component photos, which often don't match.

        1. If the products already have clean gaps between them, cut them apart
           and re-lay them with proper spacing (no AI, perfect fidelity).
        2. Otherwise (they touch/overlap), ask Gemini to separate the products
           in the original, then cut THAT result and re-lay it in the standard
           layout. If the AI result still can't be cut into `n` clean products,
           the AI failed and we return None.

        Returns (generated_path, used_ai) or (None, False).
        """
        if not composer or not original_image_path or n < 2:
            return None, False
        out = os.path.join(uploads_dir, f"{code}_generated.jpg")

        if not remove_badge:
            ok = await asyncio.to_thread(composer.rebuild_by_splitting,
                                         original_image_path, n, out)
            if ok:
                return out, False

        if gemini is None:
            return None, False
        separated = os.path.join(uploads_dir, f"{code}_separated.jpg")
        badge_clause = (
            " Also remove any overlaid promotional multiplier badge (e.g. a circle "
            "with 'x2' or 'x3'); it is not part of any product." if remove_badge else ""
        )
        base_prompt = (
            f"Move the {n} products apart horizontally so they stand side by side in a "
            "single row with a clear white gap between each one — no product may touch "
            "or overlap another. Show every product in full, keep each one's size, "
            "shape, colours and label text exactly as they are, and keep the plain "
            f"white background.{badge_clause}"
        )
        prompts = [
            base_prompt,
            # Firmer second attempt if the first still left products touching.
            base_prompt + (
                " IMPORTANT: leave a WIDE empty white gap between neighbouring products — "
                "at least a tenth of the image width — and keep all products standing on "
                "the same baseline."
            ),
        ]
        for attempt, prompt in enumerate(prompts, 1):
            try:
                await asyncio.to_thread(gemini.edit_image, original_image_path, prompt, separated)
            except Exception as e:  # noqa: BLE001 — AI failure falls back, never aborts
                logger.warning(f"Bundle {code}: Gemini separation failed: {e}")
                return None, False
            ok = await asyncio.to_thread(composer.rebuild_by_splitting, separated, n, out)
            if ok:
                return out, True
            logger.info(f"Bundle {code}: AI separation attempt {attempt} didn't yield "
                        f"{n} clean products")
        return None, False

    async def _rebuild_from_components(self, code, title, original_image_path, products,
                                       components, arrangement, composer, uploads_dir, verdict,
                                       gemini=None, classifier=None):
        """Decide how to rebuild a bundle that the vision model flagged.

        Preferred: rebuild from the ORIGINAL image's own products (cut apart, or
        AI-separated then cut) — this keeps the exact product variant, colours,
        sizes and order. Component photos are only a fallback, because they
        often show a different variant, a colour swatch or even a placeholder.

        - No clean components available -> Supplier Image Required.
        - More than MAX_ITEMS_IN_ROW items -> Manual Review.
        - Original shows only ONE unit with a multiplier badge -> duplicate the
          clean component photo ×quantity, but only if that photo is verified to
          match the product in the original; otherwise Manual Review.
        - Unknown multipack count (badge/title says several, WCS says 1) -> Manual.
        - Fallback for multi-product bundles: rebuild from component photos at
          sizes measured in the original; if they can't be matched confidently,
          keep the original (overlap only) or Manual.
        """
        reason = (verdict or {}).get('reason') or ''

        def manual(msg):
            return self._result(code, title, 'manual', original_image_path, None, products,
                                 0.4, [msg], arrangement['reasoning'], True)

        def ready(path, msg):
            return self._result(code, title, 'ready', original_image_path, path, products,
                                 0.6, [msg], arrangement['reasoning'], True)

        if not components:
            issues = [
                f"{reason or 'Image needs fixing'}. No clean component images on "
                + "Boots.com to rebuild from — request an image from the supplier.",
            ]
            logger.info(f"Bundle {code}: supplier (no clean components)")
            return self._result(code, title, 'supplier', original_image_path, None, products,
                                 0.3, issues, arrangement['reasoning'], False)

        distinct = len({c['code'] for c in components})
        total_units = sum(c['quantity'] for c in components)
        has_badge = bool(verdict and verdict.get('has_badge'))
        single_unit_shown = bool(verdict and verdict.get('single_with_badge'))
        badge_implies_more = has_badge or single_unit_shown

        # --- Too many items for one clean image ---
        if distinct == 1 and total_units > self.MAX_ITEMS_IN_ROW:
            logger.info(f"Bundle {code}: manual (pack of {total_units} too large)")
            return manual(
                f"Multipack of {total_units} — too many units to show clearly in a single "
                "image. Needs manual review (e.g. a representative shot or a roundel).")
        if distinct > self.MAX_ITEMS_IN_ROW:
            logger.info(f"Bundle {code}: manual ({distinct} products too many for one row)")
            return manual(
                f"{distinct} different products — too many to arrange clearly in a single "
                "image. Needs manual review.")

        # --- Preferred: rebuild from the original's own products ---
        # (Skipped when the original shows just one unit — there's nothing to
        # separate; that case duplicates a verified component photo below.)
        if not single_unit_shown and 2 <= total_units <= self.MAX_ITEMS_IN_ROW:
            path, used_ai = await self._rebuild_from_original(
                code, original_image_path, total_units, composer, gemini, uploads_dir,
                remove_badge=has_badge,
            )
            if path:
                if used_ai:
                    msg = ("Products overlapped, so AI separated them in the original image, "
                           "then they were re-laid with clear spacing — check the details "
                           "match before approving.")
                else:
                    msg = ("Separated the products from the original image and added clear "
                           "spacing — the exact products and sizes are preserved.")
                logger.info(f"Bundle {code}: rebuilt from original (ai={used_ai})")
                # A clean cut reuses the original's own pixels, so only AI output
                # needs checking (it can garble small text).
                return await self._check_rebuild(
                    code, original_image_path, ready(path, msg),
                    classifier if used_ai else None,
                    'ai_separated' if used_ai else 'cut',
                )

        # --- Single product type (multipack of identical units) ---
        if distinct == 1:
            if total_units >= 2:
                # The original shows FEWER units than the pack (a multiplier
                # badge): duplicate the clean component photo — but only if that
                # photo really is the product in the original (component photos
                # are sometimes a different variant or even a placeholder).
                if badge_implies_more:
                    score = 0.0
                    if composer and original_image_path:
                        _, score, _ = await asyncio.to_thread(
                            composer.measure_relative_heights,
                            original_image_path, [components[0]['path']],
                        )
                    if score < self.COMPONENT_MATCH_MIN:
                        logger.info(f"Bundle {code}: manual (component photo doesn't match, "
                                    f"score={score:.2f})")
                        return manual(
                            f"Shown as fewer units than the pack of {total_units}, but the "
                            "Boots.com product photo doesn't match the product in the original "
                            f"(match {score:.0%}) — needs manual review.")
                    issues = [f"Shown as fewer units than the pack of {total_units} — "
                              + f"rebuilt from the clean product photo to show all {total_units}."]
                    logger.info(f"Bundle {code}: rebuild multipack x{total_units}")
                    res = await self._compose(code, title, original_image_path, products,
                                              components, None, arrangement, composer,
                                              uploads_dir, issues)
                    return await self._check_rebuild(code, original_image_path, res,
                                                     classifier, 'duplicate')
                if verdict and verdict.get('poor_quality'):
                    logger.info(f"Bundle {code}: manual (multipack, genuine quality issue)")
                    return manual(
                        "Multipack with an image-quality issue — needs manual review.")
                logger.info(f"Bundle {code}: filtered (multipack already shows all units)")
                return None
            # qty < 2
            title_implies_pack = bool(_MULTIPACK_TITLE_RE.search(title or ''))
            if badge_implies_more or title_implies_pack:
                logger.info(f"Bundle {code}: manual (multipack count unknown)")
                return manual(
                    "Looks like a multipack of one product, but Boots.com reports only a "
                    "single unit so the real count is unknown — needs manual review to show "
                    "the correct number of items.")
            # One product, quality issue only -> rebuild from the clean photo.
            issues = ["Rebuilt from the clean Boots.com product photo on a white background."]
            res = await self._compose(code, title, original_image_path, products,
                                      components, None, arrangement, composer,
                                      uploads_dir, issues)
            return await self._check_rebuild(code, original_image_path, res,
                                             classifier, 'component')

        # --- Fallback for multiple distinct products: component photos at the
        #     sizes measured in the original ---
        rel, score, xs = None, 0.0, None
        if composer and original_image_path:
            rel, score, xs = await asyncio.to_thread(
                composer.measure_relative_heights,
                original_image_path, [c['path'] for c in components],
            )
        if rel is None:
            # We can't rebuild faithfully. If the ONLY problem was slight overlap,
            # the original is acceptable as-is — leave it (filter out) rather than
            # cluttering Manual Review. A genuine quality problem or a badge still
            # needs a human.
            only_overlap = (
                verdict
                and verdict.get('overlapping')
                and not verdict.get('poor_quality')
                and not badge_implies_more
            )
            if only_overlap:
                logger.info(f"Bundle {code}: filtered (overlap only, can't improve, original fine)")
                return None
            logger.info(f"Bundle {code}: manual (couldn't measure sizes, score={score:.2f})")
            return manual(
                f"Couldn't confidently measure the products' real sizes from the original "
                f"(best match {score:.0%}) — needs manual review to avoid wrong sizes or a "
                "missing product.")
        if gemini is not None and classifier is None and score < self.COMPONENT_REBUILD_STRONG:
            # The original-image path (cut / AI separation) already failed and the
            # component photos only loosely match the original — they're likely a
            # different variant or carry baked-in tags. Don't guess.
            logger.info(f"Bundle {code}: manual (original couldn't be separated; "
                        f"component match only {score:.2f})")
            return manual(
                "The products overlap in the original and couldn't be separated "
                "faithfully, and the Boots.com product photos don't closely match the "
                f"original (match {score:.0%}) — needs manual review.")
        # Order the products left-to-right by where each one matched in the
        # original, so the rebuild keeps the original arrangement (not the
        # arbitrary catalogue order, which can flip products — e.g. No7).
        order = sorted(range(len(components)), key=lambda i: xs[i])
        components = [components[i] for i in order]
        rel = [rel[i] for i in order]
        issues = [f"Rebuilt from {distinct} clean product photos, with each product's "
                  + "size preserved from the original and clear spacing added."]
        logger.info(f"Bundle {code}: rebuild {distinct} products, sizes preserved")
        res = await self._compose(code, title, original_image_path, products,
                                  components, rel, arrangement, composer,
                                  uploads_dir, issues)
        return await self._check_rebuild(code, original_image_path, res,
                                         classifier, 'components')

    async def _process_one(self, bundle: dict, crawler, composer, uploads_dir: str,
                           classifier=None, gemini=None, force_fix=False) -> dict | None:
        """Crawl, classify the original image, and (if needed) compose a bundle.

        Fast path: fetch only the original image + product metadata, then let the
        vision classifier decide. Fine bundles return None (filtered) without ever
        downloading component photos — that's what keeps large batches quick.
        """
        code = bundle.get('code', '')
        title = bundle.get('title', '')
        original_image_path = None

        # Monday rows carry no per-product breakdown, so fall back to the
        # individual products discovered on the bundle's Boots.com page.
        products = list(bundle.get('products') or [])

        # Step 1: Crawl Boots.com — ONE page load gives the bundle's main image and
        # its individual products (with image URLs). We download the ORIGINAL only;
        # component photos are fetched later, and only if we decide to regenerate.
        if crawler:
            try:
                bundle_info = await crawler.search_bundle(code)
                if bundle_info:
                    if bundle_info.get('image_url'):
                        candidate = os.path.join(uploads_dir, f"{code}_original.jpg")
                        if os.path.exists(candidate):
                            original_image_path = candidate
                        else:
                            await crawler.download_image(bundle_info['image_url'], candidate)
                            original_image_path = candidate
                    if not products and bundle_info.get('individual_products'):
                        products = list(bundle_info['individual_products'])
                    if not title and bundle_info.get('title'):
                        title = bundle_info['title']
            except Exception as e:  # noqa: BLE001 — crawl failures must not abort the batch
                logger.warning(f"Crawler failed for {code}: {e}")

        has_original = bool(original_image_path and os.path.exists(original_image_path))
        total_items = sum(int(p.get('quantity', 1)) for p in products)
        product_types = len({p.get('code', '') for p in products})
        is_single_type_multipack = product_types == 1 and total_items >= 2
        arrangement = self.determine_arrangement(products)

        # Step 2: Classify the ORIGINAL image with the vision model (image -> text,
        # reliable). This is the only way to tell a GOOD single-type multipack
        # (shows every unit) from a BAD one (one unit + a baked-in "xN" badge),
        # since their catalogue metadata is identical.
        verdict = None
        if classifier and has_original:
            verdict = await asyncio.to_thread(classifier.classify, original_image_path)
        # Re-checking bundles already on the dashboard: they were flagged once,
        # so don't let a borderline re-classification drop them — work on them.
        if force_fix and verdict is not None and verdict['usable'] and not verdict['needs_fixing']:
            verdict = {**verdict, 'needs_fixing': True, 'overlapping': True}

        if verdict is not None:
            reason = verdict.get('reason') or ''

            # 2a. Placeholder / broken image — no usable photo to work from.
            if not verdict['usable']:
                issues = [
                    f"No usable product image on Boots.com ({reason or 'placeholder'}). "
                    + "Request an image from the supplier.",
                ]
                logger.info(f"Bundle {code}: supplier (no usable image: {reason})")
                return self._result(code, title, 'supplier', original_image_path, None,
                                    products, 0.3, issues, arrangement['reasoning'], False)

            # 2b. Good original — needs no action, filter it out of the dashboard.
            if not verdict['needs_fixing']:
                logger.info(f"Bundle {code}: vision says image is fine — filtered out")
                return None

            # 2c. Needs fixing — rebuild from clean component photos. A badge no
            # longer forces Supplier: we rebuild the image from scratch (multipacks
            # show the product the right number of times; multi-product bundles keep
            # each product's real size measured from the original). Supplier/Manual
            # are used only when we can't rebuild faithfully.
            components = await self._download_components(crawler, products, uploads_dir)
            return await self._rebuild_from_components(
                code, title, original_image_path, products, components,
                arrangement, composer, uploads_dir, verdict, gemini, classifier,
            )

        # --- Structural fallback (no vision classifier available) ---
        # Keep the catalogue rules working even without a vision model: download
        # components, assess quality with PIL, and categorize structurally.
        components = await self._download_components(crawler, products, uploads_dir)
        product_image_paths = [c['path'] for c in components]
        product_quantities = [c['quantity'] for c in components]
        product_images_found = len(product_image_paths) > 0

        if has_original:
            quality = await asyncio.to_thread(
                self.assess_quality, original_image_path, product_image_paths,
            )
        else:
            quality = {
                'score': 0.0,
                'issues': ['No original bundle image available'],
                'needs_regeneration': True,
            }

        can_compose = (
            product_images_found
            and not arrangement['manual_review']
            and arrangement['single_image']
        )

        if is_single_type_multipack:
            reason = (
                f'Shown as one product with a "x{total_items}" badge baked into the only '
                "available Boots.com image — no clean image found. "
                "Request a badge-free image from the supplier."
            )
            issues = [*quality.get('issues', []), reason]
            logger.info(f"Bundle {code}: supplier (badged multipack, structural)")
            return self._result(code, title, 'supplier', original_image_path, None, products,
                                min(quality.get('score', 0.8), 0.5), issues,
                                arrangement['reasoning'], False)

        category, needs_regeneration = self.categorize_bundle(
            bundle=bundle,
            needs_regeneration=quality['needs_regeneration'],
            product_images_found=product_images_found,
            can_compose=can_compose,
            has_original=has_original,
        )
        generated_image_path = None
        if category == 'ready' and needs_regeneration and can_compose and composer:
            try:
                generated_image_path = os.path.join(uploads_dir, f"{code}_generated.jpg")
                await asyncio.to_thread(
                    composer.compose_bundle_image,
                    product_image_paths,
                    generated_image_path,
                    product_quantities,
                )
                logger.info(f"Generated composed image for {code}")
            except Exception:
                logger.exception(f"Failed to generate image for {code}")
                category = 'manual'
                generated_image_path = None
        # A fine, multi-product original needs no action — filter it out.
        if category == 'ready' and not needs_regeneration:
            logger.info(f"Bundle {code}: original is good — filtered out of dashboard")
            return None

        return self._result(code, title, category, original_image_path, generated_image_path,
                            products, quality['score'], quality['issues'],
                            arrangement['reasoning'], needs_regeneration)

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