import os
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

import httpx

from firefly_categorizer.logger import get_logger

logger = get_logger(__name__)

class FireflyClient:
    def __init__(self, base_url: str | None = None, token: str | None = None):
        self.base_url = base_url or os.getenv("FIREFLY_URL")
        self.token = token or os.getenv("FIREFLY_TOKEN")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def get_transactions(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 50,
        page: int = 1,
    ) -> dict:
        if not self.base_url or not self.token:
            logger.error("Firefly credentials missing.")
            return {"data": [], "meta": {}}

        async with httpx.AsyncClient() as client:
            try:
                # Firefly API filtering by date is via query params
                params = {
                    "limit": limit,
                    "page": page,
                    "type": "withdrawal", # Usually we categorize withdrawals
                }
                if start_date:
                    params["start"] = start_date.strftime("%Y-%m-%d")
                if end_date:
                    params["end"] = end_date.strftime("%Y-%m-%d")

                response = await client.get(f"{self.base_url}/api/v1/transactions", headers=self.headers, params=params)
                response.raise_for_status()
                data = response.json()
                return {
                    "data": data.get("data", []),
                    "meta": data.get("meta", {}).get("pagination", {})
                }
            except Exception as e:
                logger.error(f"Error fetching transactions: {e}")
                return {"data": [], "meta": {}}

    async def get_all_transactions(self, limit_per_page: int = 500) -> dict:
        """Fetch all transactions with pagination. Returns dict with transactions and metadata."""
        if not self.base_url or not self.token:
            return {"transactions": [], "total": 0}

        all_transactions = []
        page = 1
        total_count = 0
        total_pages = 1

        async with httpx.AsyncClient(timeout=60.0) as client:
            while True:
                try:
                    params = {
                        "limit": limit_per_page,
                        "page": page,
                    }
                    response = await client.get(
                        f"{self.base_url}/api/v1/transactions",
                        headers=self.headers,
                        params=params
                    )
                    response.raise_for_status()
                    data = response.json()
                    transactions = data.get("data", [])

                    if not transactions:
                        break

                    all_transactions.extend(transactions)

                    # Get pagination metadata
                    meta = data.get("meta", {}).get("pagination", {})
                    total_count = meta.get("total", len(all_transactions))
                    total_pages = meta.get("total_pages", 1)

                    logger.info(
                        f"[TRAIN] Fetched page {page}/{total_pages}: "
                        f"{len(all_transactions)}/{total_count} transactions"
                    )

                    if page >= total_pages:
                        break

                    page += 1
                except Exception as e:
                    logger.error(f"Error fetching transactions page {page}: {e}")
                    break

        return {
            "transactions": all_transactions,
            "total": total_count,
            "pages_fetched": page
        }

    async def yield_transactions(
        self, limit_per_page: int = 500
    ) -> AsyncGenerator[tuple[list[dict[str, Any]], dict[str, Any]], None]:
        """Async generator that yields pages of transactions and metadata."""
        if not self.base_url or not self.token:
            return

        page = 1
        total_pages = 1

        async with httpx.AsyncClient(timeout=60.0) as client:
            while True:
                try:
                    params = {
                        "limit": limit_per_page,
                        "page": page,
                    }
                    response = await client.get(
                        f"{self.base_url}/api/v1/transactions",
                        headers=self.headers,
                        params=params
                    )
                    response.raise_for_status()
                    data = response.json()
                    transactions = data.get("data", [])

                    if not transactions:
                        break

                    # Get pagination metadata
                    meta = data.get("meta", {}).get("pagination", {})
                    total_pages = meta.get("total_pages", 1)

                    yield transactions, meta

                    if page >= total_pages:
                        break

                    page += 1
                except Exception as e:
                    logger.error(f"Error fetching transactions page {page}: {e}")
                    break

    async def stream_all_transactions(self, limit_per_page: int = 500) -> AsyncGenerator[dict[str, Any], None]:
        """Async generator that yields progress updates while fetching transactions."""
        if not self.base_url or not self.token:
            yield {"stage": "error", "message": "Firefly credentials missing"}
            return

        all_transactions = []
        page = 1
        total_count = 0
        total_pages = 1

        async with httpx.AsyncClient(timeout=60.0) as client:
            # First request to get total count
            while True:
                try:
                    params = {"limit": limit_per_page, "page": page}
                    response = await client.get(
                        f"{self.base_url}/api/v1/transactions",
                        headers=self.headers,
                        params=params
                    )
                    response.raise_for_status()
                    data = response.json()
                    transactions = data.get("data", [])

                    if not transactions:
                        break

                    all_transactions.extend(transactions)

                    meta = data.get("meta", {}).get("pagination", {})
                    total_count = meta.get("total", len(all_transactions))
                    total_pages = meta.get("total_pages", 1)

                    # Yield fetch progress
                    yield {
                        "stage": "fetching",
                        "fetched": len(all_transactions),
                        "total": total_count,
                        "percent": round(len(all_transactions) / total_count * 100, 1) if total_count > 0 else 0
                    }

                    if page >= total_pages:
                        break
                    page += 1

                except Exception as e:
                    yield {"stage": "error", "message": str(e)}
                    return

        # Yield final fetch complete with all transactions
        yield {
            "stage": "fetch_complete",
            "transactions": all_transactions,
            "total": total_count
        }

    async def get_categories(self) -> list[dict]:
        if not self.base_url or not self.token:
            return []

        async with httpx.AsyncClient() as client:
            try:
                # Firefly API for categories
                response = await client.get(f"{self.base_url}/api/v1/categories", headers=self.headers)
                response.raise_for_status()
                data = response.json()
                return data.get("data", [])
            except Exception as e:
                logger.error(f"Error fetching categories: {e}")
                return []

    async def update_transaction(self, transaction_id: str, category_name: str) -> bool:
        if not self.base_url or not self.token:
            return False

        async with httpx.AsyncClient() as client:
            try:
                # Update transaction category
                # Payload format: { "transactions": [ { "category_name": "New Category" } ] }
                payload = {
                    "transactions": [
                        {
                            "category_name": category_name
                        }
                    ]
                }
                response = await client.put(
                    f"{self.base_url}/api/v1/transactions/{transaction_id}",
                    headers=self.headers,
                    json=payload
                )
                response.raise_for_status()
                return True
            except Exception as e:
                logger.error(f"Error updating transaction {transaction_id}: {e}")
                return False
