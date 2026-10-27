"""
Boots Bundle Image Studio — Monday.com Client
=============================================
Fetches the Commercial Core Line List and 2am Report from Monday.com,
identifies Virtual Bundle lines, and cross-references for live status.
"""

from __future__ import annotations

import asyncio
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
                # Monday returns file_extension with a leading dot (e.g. ".xlsx");
                # normalise it and also fall back to the asset's filename.
                ext = (asset.get("file_extension") or "").lower().lstrip(".")
                name = (asset.get("name") or "").lower()
                if ext in ("xlsx", "xls") or name.endswith((".xlsx", ".xls")):
                    xlsx_asset = asset
                    break
            if xlsx_asset:
                break

        if not xlsx_asset:
            raise ValueError("No .xlsx asset found in 2am report updates")

        # The asset's own `url` is a protected monday.com link that needs a login
        # session (returns 406). Resolve the public, pre-signed URL instead, the
        # same way fetch_core_line_list does.
        asset_url = await self.get_asset_url(xlsx_asset["id"])
        if not asset_url:
            asset_url = xlsx_asset.get("url")

        if not asset_url:
            raise ValueError("Could not get download URL for 2am report asset")

        await self.download_file(asset_url, save_path)
        return save_path

    @staticmethod
    def _norm_code(value) -> str:
        """Normalise a code cell to a comparable string (handles int/float cells)."""
        if value is None:
            return ""
        s = str(value).strip()
        return s.removesuffix(".0")  # numeric codes often arrive as floats

    @staticmethod
    def _find_col(headers: list, *candidates: str) -> int | None:
        """Find a column index by case-insensitive exact header match first, then
        by substring, trying each candidate name in order."""
        norm = [str(h).lower().strip() if h else "" for h in headers]
        for cand in candidates:
            c = cand.lower()
            for i, h in enumerate(norm):
                if h == c:
                    return i
        for cand in candidates:
            c = cand.lower()
            for i, h in enumerate(norm):
                if h and c in h:
                    return i
        return None

    @staticmethod
    def parse_core_line_list(file_path: str) -> list:
        """
        Parse the Commercial Core Line List Excel file.
        Returns Virtual Bundle lines. Each has:
          - code:       Boots.com Article Number (8-digit; used to crawl + export)
          - match_code: Article Number (used to cross-reference the 2am report)
          - title/name, brand, article_type
        """
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        ws = wb.active

        headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
        c_type = MondayClient._find_col(headers, "Boots.com Article Type", "Article Type")
        c_code = MondayClient._find_col(headers, "Boots.com Article Number", "Boots.com Article")
        c_match = MondayClient._find_col(headers, "Article Number")
        c_name = MondayClient._find_col(headers, "Full Article Description", "Article Description", "Description")
        c_brand = MondayClient._find_col(headers, "Brand Link", "Brand")

        if c_type is None:
            raise ValueError("Could not find an 'Article Type' column in Core Line List")

        def cell(row, idx):
            return row[idx] if idx is not None and idx < len(row) else None

        virtual_bundles = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            article_type = cell(row, c_type)
            if not (article_type and "virtual bundle" in str(article_type).lower()):
                continue
            name = str(cell(row, c_name) or "").strip()
            bundle = {
                "code": MondayClient._norm_code(cell(row, c_code)),
                "match_code": MondayClient._norm_code(cell(row, c_match)),
                "title": name,
                "name": name,
                "brand": str(cell(row, c_brand) or "").strip(),
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
        The header is not on row 1 (the first rows hold a title + blanks), so it is
        detected dynamically. Returns the set of live 'BTC Code' values, which match
        the Core Line List's 'Article Number'.
        """
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        ws = wb.active

        # Detect the header row within the first ~15 rows.
        header_row = None
        headers = None
        for idx, row in enumerate(ws.iter_rows(min_row=1, max_row=15, values_only=True), start=1):
            cells = [str(c).lower() for c in row if c]
            if any("btc code" in c or "sap code" in c for c in cells):
                header_row = idx
                headers = list(row)
                break

        if header_row is None:
            wb.close()
            raise ValueError("Could not find the header row in the 2am report")

        code_col = MondayClient._find_col(headers, "BTC Code", "Boots.com", "Code")
        if code_col is None:
            wb.close()
            raise ValueError("Could not find a code column in the 2am report")

        live_codes = set()
        for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
            code = MondayClient._norm_code(row[code_col] if code_col < len(row) else None)
            if code:
                live_codes.add(code)

        wb.close()
        return live_codes

    async def get_confirmed_live_bundles(
        self, refresh: bool = True, originals_dir: str = "./originals", phase_cb=None,
        use_local_files: bool = False,
    ) -> list:
        """
        Complete pipeline: fetch both files, identify Virtual Bundles,
        cross-reference against 2am Report, return confirmed-live bundles.

        The Core Line List is ~40MB, so the files are cached on disk and only
        re-downloaded when `refresh` is True or they are missing. Parsing (CPU-heavy
        openpyxl work) runs in a worker thread so it never blocks the event loop.
        `phase_cb(str)`, if given, is called with a human-readable phase label.

        When `use_local_files` is True, the Monday.com download is skipped entirely
        and the existing files in `originals_dir` are parsed (for local testing).
        """
        def phase(msg: str) -> None:
            if phase_cb:
                phase_cb(msg)

        core_path = os.path.join(originals_dir, "core_line_list.xlsx")
        report_path = os.path.join(originals_dir, "2am_report.xlsx")

        if use_local_files:
            missing = [p for p in (core_path, report_path) if not os.path.exists(p)]
            if missing:
                raise FileNotFoundError(
                    f"use_local_files=True but these files are missing: {missing}"
                )
            phase("Using local files (skipping Monday.com download)…")
        else:
            # Download only when asked to refresh or when the cached files are missing
            if refresh or not os.path.exists(core_path):
                phase("Downloading Core Line List (~40MB) from Monday.com…")
                await self.fetch_core_line_list(core_path)
            if refresh or not os.path.exists(report_path):
                phase("Downloading 2am report from Monday.com…")
                await self.fetch_2am_report(report_path)

        # Parse off the event loop (these block on large spreadsheets)
        phase("Parsing Core Line List…")
        virtual_bundles = await asyncio.to_thread(self.parse_core_line_list, core_path)
        phase("Parsing 2am report…")
        live_codes = await asyncio.to_thread(self.parse_2am_report, report_path)
        phase("Cross-referencing live bundles…")

        # Cross-reference: a bundle is live if its Article Number (match_code)
        # appears in the 2am report's BTC codes.
        confirmed_live = []
        for bundle in virtual_bundles:
            if bundle.get("match_code") and bundle["match_code"] in live_codes:
                bundle["live"] = True
                confirmed_live.append(bundle)

        print(f"Found {len(virtual_bundles)} Virtual Bundles, {len(confirmed_live)} confirmed live")
        return confirmed_live