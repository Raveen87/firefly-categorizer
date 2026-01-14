import os
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

import httpx

from firefly_categorizer.logger import get_logger

logger = get_logger(__name__)

def _safe_timestamp(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0

def _sort_transactions_by_created_at(transactions: list[dict[str, Any]]) -> None:
    def sort_key(tx: dict[str, Any]) -> tuple[float, str]:
        attrs = tx.get("attributes", {})
        created_at = attrs.get("created_at")
        if not created_at:
            nested = attrs.get("transactions") or []
            if nested:
                created_at = nested[0].get("created_at") or nested[0].get("date")
        if not created_at:
            created_at = attrs.get("updated_at") or attrs.get("date")
        tx_id = tx.get("id")
        return (_safe_timestamp(created_at), str(tx_id) if tx_id is not None else "")

    transactions.sort(key=sort_key)

class FireflyClient:
    def __init__(self, base_url: str | None = None, token: str | None = None):
        self.base_url = base_url or os.getenv("FIREFLY_URL")
        self.token = token or os.getenv("FIREFLY_TOKEN")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _fetch_transactions_page(
        self,
        client: httpx.AsyncClient,
        *,
        page: int,
        limit: int,
        sort_supported: bool,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
        params: dict[str, Any] = {
            "limit": limit,
            "page": page,
        }
        if sort_supported:
            params["sort"] = "created_at"
            params["order"] = "asc"

        response = await client.get(
            f"{self.base_url}/api/v1/transactions",
            headers=self.headers,
            params=params,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if sort_supported and exc.response is not None and exc.response.status_code == 400:
                sort_supported = False
                logger.warning(
                    "[TRAIN] Firefly does not support sort=created_at. Continuing without sorting."
                )
                params.pop("sort", None)
                params.pop("order", None)
                response = await client.get(
                    f"{self.base_url}/api/v1/transactions",
                    headers=self.headers,
                    params=params,
                )
                response.raise_for_status()
            else:
                raise
        data = response.json()
        transactions = data.get("data", [])
        meta = data.get("meta", {}).get("pagination", {})
        return transactions, meta, sort_supported

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
        sort_supported = True

        async with httpx.AsyncClient(timeout=60.0) as client:
            while True:
                try:
                    transactions, meta, sort_supported = await self._fetch_transactions_page(
                        client,
                        page=page,
                        limit=limit_per_page,
                        sort_supported=sort_supported,
                    )

                    if not transactions:
                        break

                    _sort_transactions_by_created_at(transactions)

                    all_transactions.extend(transactions)

                    # Get pagination metadata
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
        sort_supported = True

        async with httpx.AsyncClient(timeout=60.0) as client:
            while True:
                try:
                    transactions, meta, sort_supported = await self._fetch_transactions_page(
                        client,
                        page=page,
                        limit=limit_per_page,
                        sort_supported=sort_supported,
                    )

                    if not transactions:
                        break

                    _sort_transactions_by_created_at(transactions)

                    # Get pagination metadata
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
        sort_supported = True

        async with httpx.AsyncClient(timeout=60.0) as client:
            # First request to get total count
            while True:
                try:
                    transactions, meta, sort_supported = await self._fetch_transactions_page(
                        client,
                        page=page,
                        limit=limit_per_page,
                        sort_supported=sort_supported,
                    )

                    if not transactions:
                        break

                    _sort_transactions_by_created_at(transactions)

                    all_transactions.extend(transactions)

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

    async def get_transaction(self, transaction_id: str) -> dict[str, Any] | None:
        if not self.base_url or not self.token:
            return None

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.base_url}/api/v1/transactions/{transaction_id}",
                    headers=self.headers
                )
                response.raise_for_status()
                data = response.json()
                return data.get("data")
            except Exception as e:
                logger.error(f"Error fetching transaction {transaction_id}: {e}")
                return None

    async def update_transaction(
        self,
        transaction_id: str,
        category_name: str,
        tags: list[str] | None = None
    ) -> bool:
        if not self.base_url or not self.token:
            return False

        async with httpx.AsyncClient() as client:
            try:
                # Update transaction category
                # Payload format: { "transactions": [ { "category_name": "New Category" } ] }
                transaction_payload: dict[str, Any] = {
                    "category_name": category_name
                }
                if tags:
                    transaction_payload["tags"] = tags

                payload = {
                    "transactions": [transaction_payload]
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
