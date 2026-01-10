from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from firefly_categorizer.integration.firefly import FireflyClient


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
        mock_client = mock_client_cls.return_value
        mock_client.__aenter__.return_value = mock_client

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
async def test_train_endpoint_chunking() -> None:
    """Test that the /train endpoint processes chunks."""
    from firefly_categorizer.main import train_models

    # We need to mock the global 'firefly' and 'service' in main.py
    # But main.py imports them. We can patch them where they are used.

    with patch("firefly_categorizer.main.firefly") as mock_firefly, \
         patch("firefly_categorizer.main.service", new_callable=MagicMock) as mock_service:

        # Setup yield_transactions to return 2 batches
        batch1 = ([{"attributes": {"transactions": [{"description": "t1", "category_name": "C1"}]}}], {"total": 2})
        batch2 = ([{"attributes": {"transactions": [{"description": "t2", "category_name": "C2"}]}}], {"total": 2})

        async def mock_generator(
            limit_per_page: int = 500
        ) -> AsyncGenerator[tuple[list[dict[str, Any]], dict[str, Any]], None]:
            yield batch1
            yield batch2

        # yield_transactions should return the async generator object, not a coroutine
        mock_firefly.yield_transactions.side_effect = mock_generator

        # Run the endpoint function directly
        result = await train_models()

        assert result["status"] == "success"
        assert result["trained"] == 2
        assert result["fetched"] == 2

        # Verify service.learn was called 2 times
        assert mock_service.learn.call_count == 2

        # Verify call arguments
        # call_args_list[0] -> call(Transaction(desc="t1"), Category(name="C1"))
        args1, _ = mock_service.learn.call_args_list[0]
        assert args1[0].description == "t1"
        assert args1[1].name == "C1"

        args2, _ = mock_service.learn.call_args_list[1]
        assert args2[0].description == "t2"
        assert args2[1].name == "C2"
