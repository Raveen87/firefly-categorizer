import asyncio
import os
from collections.abc import AsyncGenerator
from datetime import datetime
from time import monotonic
from typing import Any

import httpx

from firefly_categorizer.logger import get_logger

logger = get_logger(__name__)

DEFAULT_CATEGORIES_CACHE_TTL_SECONDS = 60.0

def _parse_env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("[ENV] Invalid %s='%s', using default %.2f.", name, raw, default)
        return default

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
    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        client: httpx.AsyncClient | None = None,
        categories_cache_ttl: float | None = None,
    ):
        self.base_url = base_url or os.getenv("FIREFLY_URL")
        self.token = token or os.getenv("FIREFLY_TOKEN")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self._client = client
        self._client_lock = asyncio.Lock()
        self._cache_lock = asyncio.Lock()
        self._categories_cache: list[dict[str, Any]] | None = None
        self._categories_cache_expires_at = 0.0
        cache_ttl = categories_cache_ttl
        if cache_ttl is None:
            cache_ttl = _parse_env_float(
                "FIREFLY_CATEGORIES_TTL",
                DEFAULT_CATEGORIES_CACHE_TTL_SECONDS,
            )
        self._categories_cache_ttl = max(0.0, cache_ttl)

    def refresh(self, base_url: str | None = None, token: str | None = None) -> None:
        base_value = base_url if base_url is not None else os.getenv("FIREFLY_URL")
        token_value = token if token is not None else os.getenv("FIREFLY_TOKEN")
        self.base_url = base_value or None
        self.token = token_value or None
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self._categories_cache = None
        self._categories_cache_expires_at = 0.0
        self._categories_cache_ttl = _parse_env_float(
            "FIREFLY_CATEGORIES_TTL",
            DEFAULT_CATEGORIES_CACHE_TTL_SECONDS,
        )

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _get_client(self) -> httpx.AsyncClient:
        # Fast path: client already exists and is open
        client = self._client
        if client is not None and not client.is_closed:
            return client

        # Slow path: create or recreate client with lock protection
        async with self._client_lock:
            # Double-check after acquiring lock to avoid creating multiple clients
            client = self._client
            if client is None or client.is_closed:
                client = httpx.AsyncClient()
                self._client = client
            return client

    def _get_cached_categories(self, *, allow_stale: bool = False) -> list[dict[str, Any]] | None:
        """Internal method to check cache. Safe to call without lock for fast-path check."""
        if self._categories_cache is None or self._categories_cache_ttl <= 0:
            return None
        if allow_stale:
            return self._categories_cache
        if monotonic() >= self._categories_cache_expires_at:
            return None
        return self._categories_cache

    def _cache_categories(self, categories: list[dict[str, Any]]) -> None:
        """Internal method to update cache. Must be called while holding _cache_lock."""
        if self._categories_cache_ttl <= 0:
            return
        self._categories_cache = categories
        self._categories_cache_expires_at = monotonic() + self._categories_cache_ttl

    async def _fetch_transactions_page(
        self,
        client: httpx.AsyncClient,
        *,
        page: int,
        limit: int,
        sort_supported: bool,
        timeout: float | None = 60.0,
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
            timeout=timeout,
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
                    timeout=timeout,
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

        client = await self._get_client()
        try:
            # Firefly API filtering by date is via query params
            params = {
                "limit": limit,
                "page": page,
                "type": "withdrawal", # Only work with withdrawals
            }
            if start_date:
                params["start"] = start_date.strftime("%Y-%m-%d")
            if end_date:
                params["end"] = end_date.strftime("%Y-%m-%d")

            response = await client.get(
                f"{self.base_url}/api/v1/transactions",
                headers=self.headers,
                params=params,
            )
            response.raise_for_status()
            data = response.json()
            return {
                "data": data.get("data", []),
                "meta": data.get("meta", {}).get("pagination", {})
            }
        except Exception as exc:
            logger.error("Error fetching transactions: %s", exc)
            return {"data": [], "meta": {}}

    async def get_all_transactions(self, limit_per_page: int = 500) -> dict:
        """Fetch all transactions with pagination. Returns dict with transactions and metadata."""
        if not self.base_url or not self.token:
            return {"transactions": [], "total": 0}

        all_transactions = []
        page = 1
        total_count = 0
        sort_supported = True

        client = await self._get_client()
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
                    "[TRAIN] Fetched page %s/%s: %s/%s transactions",
                    page,
                    total_pages,
                    len(all_transactions),
                    total_count,
                )

                if page >= total_pages:
                    break

                page += 1
            except Exception as exc:
                logger.error("Error fetching transactions page %s: %s", page, exc)
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
        sort_supported = True

        client = await self._get_client()
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
            except Exception as exc:
                logger.error("Error fetching transactions page %s: %s", page, exc)
                break

    async def stream_all_transactions(self, limit_per_page: int = 500) -> AsyncGenerator[dict[str, Any], None]:
        """Async generator that yields progress updates while fetching transactions."""
        if not self.base_url or not self.token:
            yield {"stage": "error", "message": "Firefly credentials missing"}
            return

        all_transactions = []
        page = 1
        total_count = 0
        sort_supported = True

        client = await self._get_client()
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

            except Exception as exc:
                yield {"stage": "error", "message": str(exc)}
                return

        # Yield final fetch complete with all transactions
        yield {
            "stage": "fetch_complete",
            "transactions": all_transactions,
            "total": total_count
        }

    async def _fetch_categories_from_api(self, client: httpx.AsyncClient) -> list[dict]:
        """Fetch categories from Firefly API."""
        response = await client.get(
            f"{self.base_url}/api/v1/categories",
            headers=self.headers,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("data", [])

    async def get_categories(self, *, use_cache: bool = True) -> list[dict]:
        if not self.base_url or not self.token:
            return []

        if use_cache:
            # Acquire lock for all cache operations to prevent race conditions
            async with self._cache_lock:
                # Check cache
                cached = self._get_cached_categories()
                if cached is not None:
                    return cached

                # Cache miss or expired - fetch from API
                client = await self._get_client()
                try:
                    categories = await self._fetch_categories_from_api(client)
                    self._cache_categories(categories)
                    return categories
                except Exception as exc:
                    logger.error("Error fetching categories: %s", exc)
                    cached = self._get_cached_categories(allow_stale=True)
                    if cached is not None:
                        return cached
                    return []
        else:
            # No caching - fetch directly
            client = await self._get_client()
            try:
                categories = await self._fetch_categories_from_api(client)
                return categories
            except Exception as exc:
                logger.error("Error fetching categories: %s", exc)
                return []

    async def get_transaction(self, transaction_id: str) -> dict[str, Any] | None:
        if not self.base_url or not self.token:
            return None

        client = await self._get_client()
        try:
            response = await client.get(
                f"{self.base_url}/api/v1/transactions/{transaction_id}",
                headers=self.headers,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("data")
        except Exception as exc:
            logger.error("Error fetching transaction %s: %s", transaction_id, exc)
            return None

    async def update_transaction(
        self,
        transaction_id: str,
        category_name: str,
        tags: list[str] | None = None
    ) -> bool:
        if not self.base_url or not self.token:
            return False

        client = await self._get_client()
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
                json=payload,
            )
            response.raise_for_status()
            return True
        except Exception as exc:
            logger.error("Error updating transaction %s: %s", transaction_id, exc)
            return False
