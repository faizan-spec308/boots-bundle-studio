"""
Boots Bundle Image Studio — Boots.com Crawler
=============================================
Searches Boots.com for specific bundle products, downloads images,
and identifies individual products within bundles.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

X_AGENT_CLIENT = os.getenv("BOOTS_X_AGENT_CLIENT", "W-7njoVr89mFAk")

# Boots.com product sitemap (server-rendered XML; maps products -> page URLs).
SITEMAP_URL = "https://www.boots.com/wcsstore/eBootsStorefrontAssetStore/sitemap/uk-product-sitemap.xml"
# Scene7 serves every product image deterministically by its 8-digit code.
SCENE7_BASE = "https://boots.scene7.com/is/image/Boots"
# Boots WCS catalog API — returns JSON directly, including a bundle's components
# with their real quantities (the sitemap/HTML path can't give quantities).
WCS_BASE = "https://www.boots.com/search/resources/store/11352/productview"


class BootsCrawler:
    def __init__(self, x_agent_client: str | None = None, cache_dir: str = "originals"):
        self.x_agent_client = x_agent_client or X_AGENT_CLIENT
        self.cache_dir = cache_dir
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
        }
        # A single shared, connection-pooled client reused across all requests
        # (much faster than creating a new client per request under concurrency).
        self._client = httpx.AsyncClient(
            headers=self.headers,
            follow_redirects=True,
            timeout=30,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        self._code_to_url: dict | None = None  # product code -> page URL (from sitemap)
        self._sitemap_lock = asyncio.Lock()

    async def close(self) -> None:
        """Close the shared HTTP client. Call on application shutdown."""
        await self._client.aclose()

    def image_url(self, code: str) -> str:
        """Deterministic Scene7 image URL for a product/bundle code."""
        return f"{SCENE7_BASE}/{code}?fmt=jpg&wid=1500&hei=1500&fit=constrain,1"

    async def _ensure_sitemap(self) -> None:
        """Load the product sitemap into a code->URL map (cached in memory + on
        disk for 24h). The search page is JS-rendered, so the sitemap is how we
        resolve a bundle code to its real product-page URL."""
        if self._code_to_url is not None:
            return
        async with self._sitemap_lock:
            if self._code_to_url is not None:
                return
            cache_path = os.path.join(self.cache_dir, "boots_sitemap.json")
            if os.path.exists(cache_path) and time.time() - os.path.getmtime(cache_path) < 86400:
                try:
                    with open(cache_path) as f:  # noqa: ASYNC230 — small cache read
                        self._code_to_url = json.load(f)
                    logger.info(f"Loaded Boots sitemap from cache ({len(self._code_to_url)} products)")
                    return
                except (json.JSONDecodeError, OSError):
                    pass

            mapping: dict = {}
            try:
                url = f"{SITEMAP_URL}?x-agent-client={self.x_agent_client}"
                resp = await self._client.get(url, timeout=60)
                resp.raise_for_status()
                for loc in re.findall(r"<loc>(.*?)</loc>", resp.text):
                    m = re.search(r"(\d{8})", loc)
                    if m:
                        mapping.setdefault(m.group(1), loc)
                logger.info(f"Downloaded Boots sitemap: {len(mapping)} products")
            except httpx.HTTPError as e:
                logger.warning(f"Failed to download Boots sitemap: {e}")

            self._code_to_url = mapping
            if mapping:
                try:
                    os.makedirs(self.cache_dir, exist_ok=True)
                    with open(cache_path, "w") as f:  # noqa: ASYNC230 — small cache write
                        json.dump(mapping, f)
                except OSError:
                    pass

    async def search_bundle(self, product_code: str) -> dict | None:
        """Resolve a bundle by its code. Primary source is the Boots WCS catalog
        API, which returns the bundle's components WITH their real quantities.
        Falls back to the product sitemap + Scene7 (quantities default to 1) when
        the API can't resolve the code."""
        result = await self._search_bundle_wcs(product_code)
        if result is not None:
            return result
        return await self._search_bundle_sitemap(product_code)

    async def _search_bundle_wcs(self, product_code: str) -> dict | None:
        """Resolve a bundle and its components (with real quantities) via WCS."""
        entry = await self._wcs_get(f"{WCS_BASE}/bySearchTerm/{product_code}")
        ce = (entry or {}).get("catalogEntryView") or []
        if not ce:
            return None
        bundle = ce[0]
        unique_id = bundle.get("uniqueID")
        products = await self._wcs_components(unique_id) if unique_id else []
        if not products:
            return None  # fall back to the sitemap path if we got no components
        return {
            "code": product_code,
            "title": bundle.get("name") or "",
            "image_url": self.image_url(product_code),
            "product_url": bundle.get("resourceId", ""),
            "individual_products": products,
        }

    async def _wcs_components(self, unique_id: str) -> list:
        """Fetch a bundle's components (partNumber, quantity, name) via byId.
        Each component's image is the deterministic Scene7 URL."""
        data = await self._wcs_get(f"{WCS_BASE}/byId/{unique_id}")
        comps = self._find_key(data, "components") if data else None
        products = []
        for comp in comps or []:
            part = comp.get("partNumber")
            if not part:
                continue
            try:
                qty = int(float(str(comp.get("quantity", "1")).strip() or "1"))
            except (TypeError, ValueError):
                qty = 1
            products.append({
                "code": str(part),
                "name": comp.get("shortDescription") or comp.get("name") or "",
                "quantity": max(1, qty),
                "image_url": self.image_url(str(part)),
            })
        return products

    async def _wcs_get(self, url: str) -> dict | None:
        """GET a WCS API URL and return parsed JSON (or None on failure)."""
        try:
            resp = await self._client.get(url, params={"x-agent-client": self.x_agent_client})
            if resp.status_code != 200:
                return None
            return resp.json()
        except (httpx.HTTPError, json.JSONDecodeError, ValueError) as e:
            logger.warning(f"WCS request failed ({url.rsplit('/', 1)[-1]}): {e}")
            return None

    @staticmethod
    def _find_key(obj, key, depth: int = 0):
        """Recursively find the first value for `key` in a nested dict/list."""
        if depth > 5:
            return None
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
            for value in obj.values():
                found = BootsCrawler._find_key(value, key, depth + 1)
                if found is not None:
                    return found
        elif isinstance(obj, list):
            for value in obj:
                found = BootsCrawler._find_key(value, key, depth + 1)
                if found is not None:
                    return found
        return None

    async def _search_bundle_sitemap(self, product_code: str) -> dict | None:
        """Fallback: resolve via the product sitemap + Scene7. Component quantities
        default to 1 (extracted from the page's Scene7 references)."""
        await self._ensure_sitemap()
        product_url = (self._code_to_url or {}).get(product_code)

        if not product_url:
            return await self._search_bundle_legacy(product_code)

        full_url = f"{product_url}?x-agent-client={self.x_agent_client}"
        html = ""
        try:
            resp = await self._client.get(full_url)
            if resp.status_code == 200:
                html = resp.text
        except httpx.HTTPError as e:
            logger.warning(f"Failed to fetch product page for {product_code}: {e}")

        return {
            "code": product_code,
            "title": self._extract_title_from_html(html),
            "image_url": self.image_url(product_code),
            "product_url": full_url,
            "individual_products": self._extract_components(html, product_code),
        }

    def _extract_components(self, html: str, bundle_code: str) -> list:
        """Extract the bundle's component products from Scene7 image references on
        the page. Each distinct 8-digit code (other than the bundle's own) is a
        component; its image is the deterministic Scene7 URL."""
        products = []
        seen = set()
        for code in re.findall(r"scene7\.com/is/image/Boots/(\d{8})", html):
            if code == bundle_code or code in seen:
                continue
            seen.add(code)
            products.append({
                "code": code,
                "name": "",
                "quantity": 1,
                "image_url": self.image_url(code),
            })
        return products

    def _extract_title_from_html(self, html: str) -> str:
        """Best-effort page title (Monday usually supplies the real title)."""
        if not html:
            return ""
        m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if m:
            return re.sub(r"\s*\|\s*BOOTS.*$", "", m.group(1).strip(), flags=re.IGNORECASE)
        return ""

    async def _search_bundle_legacy(self, product_code: str) -> dict | None:
        """Legacy fallback: the old JS-rendered site search (rarely finds a link,
        kept for codes missing from the sitemap)."""
        search_url = f"https://www.boots.com/sitesearch?searchTerm={product_code}&x-agent-client={self.x_agent_client}"
        resp = await self._client.get(search_url)
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        product_link = None
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/product/" in href or re.search(r"/\d{8}", href):
                product_link = href if href.startswith("http") else f"https://www.boots.com{href}"
                break
        if not product_link:
            return None

        product_url = f"{product_link}?x-agent-client={self.x_agent_client}"
        resp2 = await self._client.get(product_url)
        if resp2.status_code != 200:
            return None

        product_soup = BeautifulSoup(resp2.text, "html.parser")
        return {
            "code": self._extract_bundle_code(product_url),
            "title": self._extract_title(product_soup),
            "image_url": self._extract_main_image(product_soup),
            "product_url": product_url,
            "individual_products": self._extract_individual_products(product_soup),
        }

    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Extract the product title from the page."""
        # Try JSON-LD first
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                import json
                data = json.loads(script.string)
                if isinstance(data, list):
                    data = data[0]
                if data.get("name"):
                    return data["name"]
            except (json.JSONDecodeError, TypeError):
                pass

        # Fallback to og:title
        og_title = soup.find("meta", property="og:title")
        if og_title:
            return og_title.get("content", "")

        # Fallback to h1
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)

        return ""

    def _extract_main_image(self, soup: BeautifulSoup) -> str | None:
        """Extract the main product image URL."""
        # Try JSON-LD
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                import json
                data = json.loads(script.string)
                if isinstance(data, list):
                    data = data[0]
                if data.get("image"):
                    img = data["image"]
                    if isinstance(img, list):
                        return img[0]
                    return img
            except (json.JSONDecodeError, TypeError):
                pass

        # Try og:image
        og_image = soup.find("meta", property="og:image")
        if og_image:
            return og_image.get("content")

        # Try first product image
        for img in soup.find_all("img", src=True):
            src = img["src"]
            if "product" in src.lower() or "image" in src.lower():
                if src.startswith("//"):
                    return f"https:{src}"
                elif src.startswith("/"):
                    return f"https://www.boots.com{src}"
                return src

        return None

    def _extract_bundle_code(self, url: str) -> str:
        """Extract the 8-digit bundle code from the product URL."""
        match = re.search(r"(\d{8})", url)
        return match.group(1) if match else ""

    def _extract_individual_products(self, soup: BeautifulSoup) -> list:
        """Extract individual product details from the bundle page."""
        products = []

        # Look for product references in the description
        desc_div = soup.find("div", class_=re.compile("product-description|product-details|description"))
        if desc_div:
            desc_div.get_text()

        # Look for JSON-LD with includes
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                import json
                data = json.loads(script.string)
                if isinstance(data, list):
                    data = data[0]
                # Check for isBundleOf or includes
                includes = data.get("isBundleOf") or data.get("includes") or []
                for item in includes:
                    img = item.get("image")
                    if isinstance(img, list):
                        img = img[0] if img else None
                    products.append({
                        "name": item.get("name", ""),
                        "code": str(item.get("sku", "")),
                        "quantity": 1,
                        "image_url": img,
                    })
            except (json.JSONDecodeError, TypeError):
                pass

        # Fallback: look for product links in the description
        if not products:
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/product/" in href:
                    code_match = re.search(r"(\d{8})", href)
                    products.append({
                        "name": a.get_text(strip=True),
                        "code": code_match.group(1) if code_match else "",
                        "quantity": 1,
                    })

        return products

    async def download_image(self, url: str, save_path: str) -> str:
        """Download an image from a URL and save it locally."""
        resp = await self._client.get(url, timeout=60)
        resp.raise_for_status()
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        with open(save_path, "wb") as f:  # noqa: ASYNC230 — small one-shot image write
            f.write(resp.content)
        return save_path

    async def download_product_image(self, product_code: str, image_url: str | None, save_dir: str) -> str | None:
        """Download a product image by URL, skipping the network if it's already
        cached on disk. Returns the local path or None."""
        save_path = os.path.join(save_dir, f"{product_code}.jpg")
        if os.path.exists(save_path):
            return save_path
        if not image_url:
            return None
        try:
            return await self.download_image(image_url, save_path)
        except (httpx.HTTPError, OSError):
            return None

    async def get_product_image(self, product_code: str, save_dir: str) -> str | None:
        """Search for an individual product and download its main image.
        Returns the cached path immediately if the image already exists."""
        save_path = os.path.join(save_dir, f"{product_code}.jpg")
        if os.path.exists(save_path):
            return save_path
        result = await self.search_bundle(product_code)
        if result and result.get("image_url"):
            await self.download_image(result["image_url"], save_path)
            return save_path
        return None