"""
Boots Bundle Image Studio — Monday.com Client
=============================================
Fetches the Commercial Core Line List and 2am Report from Monday.com,
identifies Virtual Bundle lines, and cross-references for live status.
"""

from __future__ import annotations

import os

import httpx
import openpyxl


class MondayClient:
    def __init__(self, api_token: str, board_id: int = 5100428483):
        self.api_token = api_token
        self.board_id = board_id
        self.base_url = "https://api.monday.com/v2"
        self.headers = {"Authorization": api_token, "Content-Type": "application/json"}

    async def _graphql(self, query: str, variables: dict | None = None) -> dict:
        """Execute a GraphQL query against Monday.com API."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self.base_url,
                json={"query": query, "variables": variables or {}},
                headers=self.headers,
                timeout=60,
            )
            resp.raise_for_status()
            result = resp.json()
            # Monday returns HTTP 200 even for query errors, with the details
            # under "errors" (and often no "data"). Surface them clearly instead
            # of letting callers trip over a KeyError on result["data"].
            if result.get("errors"):
                raise ValueError(f"Monday API error: {result['errors']}")
            return result

    async def get_board_items(self, limit: int = 500) -> list:
        """Fetch all items from the Data Files board."""
        query = """
        query GetBoardItems($boardId: ID!, $limit: Int!) {
            boards(ids: [$boardId]) {
                items_page(limit: $limit) {
                    items {
                        id
                        name
                        created_at
                        updated_at
                        group { id title }
                        column_values {
                            id
                            text
                            value
                        }
                    }
                }
            }
        }
        """
        data = await self._graphql(query, {"boardId": str(self.board_id), "limit": limit})
        items = data["data"]["boards"][0]["items_page"]["items"]
        return items

    async def get_item_updates(self, item_id: str) -> list:
        """Fetch updates (with assets) for a specific item."""
        query = """
        query GetUpdates($itemId: ID!) {
            items(ids: [$itemId]) {
                updates {
                    id
                    body
                    created_at
                    assets {
                        id
                        name
                        url
                        file_extension
                    }
                }
            }
        }
        """
        data = await self._graphql(query, {"itemId": str(item_id)})
        items = data["data"]["items"]
        if not items:
            return []
        return items[0].get("updates", [])

    async def get_asset_url(self, asset_id: str) -> str:
        """Get the public download URL for an asset."""
        query = """
        query GetAssets($ids: [ID!]!) {
            assets(ids: $ids) {
                id
                name
                url
                public_url
            }
        }
        """
        data = await self._graphql(query, {"ids": [str(asset_id)]})
        assets = data["data"]["assets"]
        if assets:
            return assets[0].get("public_url") or assets[0].get("url")
        return None

    async def download_file(self, url: str, save_path: str) -> str:
        """Download a file from a URL and save it locally."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, follow_redirects=True, timeout=120)
            resp.raise_for_status()
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "wb") as f:  # noqa: ASYNC230 — small one-shot file download
                f.write(resp.content)
        return save_path

    def _extract_asset_id_from_file_column(self, column_value: str) -> str | None:
        """Extract the asset ID from a file column value URL."""
        if not column_value:
            return None
        # URL format: https://boots872563.monday.com/protected_static/.../resources/286883288/...
        import re
        match = re.search(r"/resources/(\d+)/", column_value)
        if match:
            return match.group(1)
        return None

    async def fetch_core_line_list(self, save_path: str = "./originals/core_line_list.xlsx") -> str:
        """
        Download the latest Commercial Core Line List Excel file.
        Returns the local file path.
        """
        items = await self.get_board_items()

        # Find the "Commercial Core Line List" item
        core_item = None
        for item in items:
            if "commercial core line list" in item["name"].lower():
                core_item = item
                break

        if not core_item:
            raise ValueError("Could not find 'Commercial Core Line List' item on the board")

        # Extract asset ID from the file column
        asset_id = None
        for cv in core_item["column_values"]:
            if cv["id"] == "file_mm59t65c":
                asset_id = self._extract_asset_id_from_file_column(cv.get("text", ""))
                if not asset_id and cv.get("value"):
                    import json
                    try:
                        val = json.loads(cv["value"])
                        if val.get("files"):
                            asset_id = str(val["files"][0].get("assetId"))
                    except (json.JSONDecodeError, KeyError):
                        pass
                break

        if not asset_id:
            raise ValueError("Could not extract asset ID from file column")

        # Get the public URL and download
        public_url = await self.get_asset_url(asset_id)
        if not public_url:
            raise ValueError("Could not get public URL for asset")

        await self.download_file(public_url, save_path)
        return save_path

    async def fetch_2am_report(self, save_path: str = "./originals/2am_report.xlsx") -> str:
        """
        Download the latest 2am Report (BOBJ Morning Report).
        Uses the most recently created "2am report" item.
        """
        items = await self.get_board_items()

        # Find all "2am report" items and pick the most recently created
        report_items = [item for item in items if "2am report" in item["name"].lower()]
        if not report_items:
            raise ValueError("Could not find any '2am report' item on the board")

        # Sort by created_at descending
        report_items.sort(key=lambda x: x["created_at"], reverse=True)
        latest_report = report_items[0]

        # Get updates with assets for this item
        updates = await self.get_item_updates(latest_report["id"])

        # Find the most recent update with an .xlsx asset
        xlsx_asset = None
        for update in reversed(updates):
            for asset in update.get("assets", []):
                if asset.get("file_extension", "").lower() in ("xlsx", "xls"):
                    xlsx_asset = asset
                    break
            if xlsx_asset:
                break

        if not xlsx_asset:
            raise ValueError("No .xlsx asset found in 2am report updates")

        # Download using the asset URL
        asset_url = xlsx_asset.get("url")
        if not asset_url:
            asset_url = await self.get_asset_url(xlsx_asset["id"])

        if not asset_url:
            raise ValueError("Could not get download URL for 2am report asset")

        await self.download_file(asset_url, save_path)
        return save_path

    @staticmethod
    def parse_core_line_list(file_path: str) -> list:
        """
        Parse the Commercial Core Line List Excel file.
        Returns a list of Virtual Bundle lines with product details.
        """
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        ws = wb.active

        # Find the header row
        headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
        header_map = {}
        for i, h in enumerate(headers):
            if h:
                h_lower = str(h).lower().strip()
                if "article" in h_lower and "type" in h_lower:
                    header_map["article_type"] = i
                elif "article" in h_lower and "number" in h_lower or "sap" in h_lower or "product" in h_lower and "code" in h_lower:
                    header_map["product_code"] = i
                elif "product" in h_lower and "name" in h_lower or "description" in h_lower:
                    header_map["product_name"] = i
                elif "brand" in h_lower:
                    header_map["brand"] = i

        if "article_type" not in header_map:
            raise ValueError("Could not find 'Article Type' column in Core Line List")

        # Collect Virtual Bundle lines
        virtual_bundles = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            article_type = row[header_map["article_type"]] if header_map["article_type"] < len(row) else None
            if article_type and "virtual bundle" in str(article_type).lower():
                bundle = {
                    "code": str(row[header_map["product_code"]]) if "product_code" in header_map and header_map["product_code"] < len(row) else "",
                    "name": str(row[header_map["product_name"]]) if "product_name" in header_map and header_map["product_name"] < len(row) else "",
                    "brand": str(row[header_map["brand"]]) if "brand" in header_map and header_map["brand"] < len(row) else "",
                    "article_type": "Virtual Bundle",
                }
                if bundle["code"]:
                    virtual_bundles.append(bundle)

        wb.close()
        return virtual_bundles

    @staticmethod
    def parse_2am_report(file_path: str) -> set:
        """
        Parse the 2am Report Excel file.
        Returns a set of product codes that are currently live on Boots.com.
        """
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        ws = wb.active

        # Find the header row and the column with product codes
        headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
        code_col = None
        for i, h in enumerate(headers):
            if h:
                h_lower = str(h).lower().strip()
                if "article" in h_lower and "number" in h_lower or "sap" in h_lower or "product" in h_lower and "code" in h_lower or "sku" in h_lower:
                    code_col = i
                    break

        if code_col is None:
            # Try first column as fallback
            code_col = 0

        live_codes = set()
        for row in ws.iter_rows(min_row=2, values_only=True):
            code = row[code_col] if code_col < len(row) else None
            if code:
                live_codes.add(str(code).strip())

        wb.close()
        return live_codes

    async def get_confirmed_live_bundles(self) -> list:
        """
        Complete pipeline: fetch both files, identify Virtual Bundles,
        cross-reference against 2am Report, return confirmed-live bundles.
        """
        core_path = "./originals/core_line_list.xlsx"
        report_path = "./originals/2am_report.xlsx"

        # Download both files fresh
        await self.fetch_core_line_list(core_path)
        await self.fetch_2am_report(report_path)

        # Parse
        virtual_bundles = self.parse_core_line_list(core_path)
        live_codes = self.parse_2am_report(report_path)

        # Cross-reference
        confirmed_live = []
        for bundle in virtual_bundles:
            if bundle["code"] in live_codes:
                bundle["live"] = True
                confirmed_live.append(bundle)

        print(f"Found {len(virtual_bundles)} Virtual Bundles, {len(confirmed_live)} confirmed live")
        return confirmed_live