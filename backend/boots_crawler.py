"""
Boots Bundle Image Studio — Boots.com Crawler
=============================================
Searches Boots.com for specific bundle products, downloads images,
and identifies individual products within bundles.
"""

from __future__ import annotations

import os
import re

import httpx
from bs4 import BeautifulSoup

X_AGENT_CLIENT = os.getenv("BOOTS_X_AGENT_CLIENT", "W-7njoVr89mFAk")


class BootsCrawler:
    def __init__(self, x_agent_client: str | None = None):
        self.x_agent_client = x_agent_client or X_AGENT_CLIENT
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
        }

    async def search_bundle(self, product_code: str) -> dict | None:
        """Search Boots.com for a specific bundle by product code."""
        search_url = f"https://www.boots.com/sitesearch?searchTerm={product_code}&x-agent-client={self.x_agent_client}"

        async with httpx.AsyncClient() as client:
            resp = await client.get(search_url, headers=self.headers, follow_redirects=True, timeout=30)
            if resp.status_code != 200:
                return None

            html = resp.text
            soup = BeautifulSoup(html, "html.parser")

            # Find the first product link
            product_link = None
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/product/" in href or re.search(r"/\d{8}", href):
                    product_link = href if href.startswith("http") else f"https://www.boots.com{href}"
                    break

            if not product_link:
                return None

            # Fetch the product page
            product_url = f"{product_link}?x-agent-client={self.x_agent_client}"
            resp2 = await client.get(product_url, headers=self.headers, follow_redirects=True, timeout=30)
            if resp2.status_code != 200:
                return None

            product_html = resp2.text
            product_soup = BeautifulSoup(product_html, "html.parser")

            # Extract product details
            title = self._extract_title(product_soup)
            image_url = self._extract_main_image(product_soup)
            bundle_code = self._extract_bundle_code(product_url)
            individual_products = self._extract_individual_products(product_soup)

            return {
                "code": bundle_code,
                "title": title,
                "image_url": image_url,
                "product_url": product_url,
                "individual_products": individual_products,
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
                    products.append({
                        "name": item.get("name", ""),
                        "code": str(item.get("sku", "")),
                        "quantity": 1,
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
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=self.headers, follow_redirects=True, timeout=60)
            resp.raise_for_status()
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "wb") as f:  # noqa: ASYNC230 — small one-shot image write
                f.write(resp.content)
        return save_path

    async def get_product_image(self, product_code: str, save_dir: str) -> str | None:
        """Search for an individual product and download its main image."""
        result = await self.search_bundle(product_code)
        if result and result.get("image_url"):
            save_path = os.path.join(save_dir, f"{product_code}.jpg")
            await self.download_image(result["image_url"], save_path)
            return save_path
        return None