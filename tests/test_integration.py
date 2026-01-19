from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from firefly_categorizer.integration.firefly import FireflyClient


def _categories_response(categories: list[dict[str, Any]]) -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"data": categories}
    return response


@pytest.mark.anyio
async def test_firefly_yield_transactions() -> None:
    """Test that yield_transactions yields pages correctly."""
    client = FireflyClient(base_url="http://test", token="token")

    # Mock response data for 2 pages
    page1_data = {
        "data": [{"id": "1", "attributes": {"transactions": [{"description": "t1"}]}}],
        "meta": {"pagination": {"total": 2, "total_pages": 2}}
    }
    page2_data = {
        "data": [{"id": "2", "attributes": {"transactions": [{"description": "t2"}]}}],
        "meta": {"pagination": {"total": 2, "total_pages": 2}}
    }

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client_cls.return_value = mock_client

        # Setup responses for 2 calls
        mock_resp1 = MagicMock()
        mock_resp1.json.return_value = page1_data
        mock_resp1.raise_for_status.return_value = None

        mock_resp2 = MagicMock()
        mock_resp2.json.return_value = page2_data
        mock_resp2.raise_for_status.return_value = None

        # Use AsyncMock for the get method so it can be awaited
        mock_client.get = AsyncMock(side_effect=[mock_resp1, mock_resp2])

        # Consume the generator
        pages = []
        async for txs, meta in client.yield_transactions(limit_per_page=1):
            pages.append((txs, meta))

        assert len(pages) == 2
        assert len(pages[0][0]) == 1
        assert pages[0][0][0]["id"] == "1"
        assert pages[0][1]["total"] == 2

    assert len(pages[1][0]) == 1
    assert pages[1][0][0]["id"] == "2"


@pytest.mark.anyio
async def test_firefly_categories_cache_ttl_expires() -> None:
    """Fetch again after TTL expiration."""
    categories_first = [{"id": "1", "attributes": {"name": "Food"}}]
    categories_second = [{"id": "2", "attributes": {"name": "Fuel"}}]

    mock_client = AsyncMock()
    mock_client.is_closed = False
    mock_client.get = AsyncMock(
        side_effect=[
            _categories_response(categories_first),
            _categories_response(categories_second),
        ]
    )

    client = FireflyClient(
        base_url="http://test",
        token="token",
        client=mock_client,
        categories_cache_ttl=1,
    )

    with patch(
        "firefly_categorizer.integration.firefly.monotonic",
        side_effect=[0.0, 2.0, 2.0],
    ):
        first = await client.get_categories()
        second = await client.get_categories()

    assert first == categories_first
    assert second == categories_second
    assert mock_client.get.call_count == 2


@pytest.mark.anyio
async def test_firefly_categories_cache_refresh_invalidates() -> None:
    """Refresh should clear the cache and force a refetch."""
    categories_first = [{"id": "1", "attributes": {"name": "Food"}}]
    categories_second = [{"id": "2", "attributes": {"name": "Fuel"}}]

    mock_client = AsyncMock()
    mock_client.is_closed = False
    mock_client.get = AsyncMock(
        side_effect=[
            _categories_response(categories_first),
            _categories_response(categories_second),
        ]
    )

    client = FireflyClient(
        base_url="http://test",
        token="token",
        client=mock_client,
        categories_cache_ttl=60,
    )

    with patch(
        "firefly_categorizer.integration.firefly.monotonic",
        side_effect=[0.0, 10.0],
    ):
        first = await client.get_categories()
        client.refresh()
        second = await client.get_categories()

    assert first == categories_first
    assert second == categories_second
    assert mock_client.get.call_count == 2


@pytest.mark.anyio
async def test_firefly_categories_cache_stale_fallback_on_error() -> None:
    """Return stale cache when the refetch fails."""
    categories = [{"id": "1", "attributes": {"name": "Food"}}]

    mock_client = AsyncMock()
    mock_client.is_closed = False
    mock_client.get = AsyncMock(
        side_effect=[
            _categories_response(categories),
            RuntimeError("boom"),
        ]
    )

    client = FireflyClient(
        base_url="http://test",
        token="token",
        client=mock_client,
        categories_cache_ttl=1,
    )

    with patch(
        "firefly_categorizer.integration.firefly.monotonic",
        side_effect=[0.0, 2.0],
    ):
        first = await client.get_categories()
        second = await client.get_categories()

    assert first == categories
    assert second == categories
    assert mock_client.get.call_count == 2

@pytest.mark.anyio
async def test_train_endpoint_chunking() -> None:
    """Test that the /train endpoint processes chunks."""
    from firefly_categorizer.services.training import TrainingManager

    mock_firefly = MagicMock()
    mock_service = MagicMock()

    batch1 = (
        [{
            "id": "1",
            "attributes": {
                "transactions": [{
                    "description": "t1",
                    "category_name": "C1",
                    "amount": 1.0,
                    "date": "2024-01-01",
                }],
            },
        }],
        {"total": 2},
    )
    batch2 = (
        [{
            "id": "2",
            "attributes": {
                "transactions": [{
                    "description": "t2",
                    "category_name": "C2",
                    "amount": 2.0,
                    "date": "2024-01-02",
                }],
            },
        }],
        {"total": 2},
    )

    async def mock_generator(
        limit_per_page: int = 500
    ) -> AsyncGenerator[tuple[list[dict[str, Any]], dict[str, Any]], None]:
        yield batch1
        yield batch2

    mock_firefly.yield_transactions.side_effect = mock_generator

    training_manager = TrainingManager(
        service=mock_service,
        firefly=mock_firefly,
        page_size=500,
    )

    result = await training_manager.train_bulk()

    assert result["status"] == "success"
    assert result["trained"] == 2
    assert result["fetched"] == 2

    assert mock_service.learn.call_count == 2

    args1, _ = mock_service.learn.call_args_list[0]
    assert args1[0].description == "t1"
    assert args1[1].name == "C1"

    args2, _ = mock_service.learn.call_args_list[1]
    assert args2[0].description == "t2"
    assert args2[1].name == "C2"
