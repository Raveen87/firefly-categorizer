import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from firefly_categorizer.integration.firefly import FireflyClient, FireflyConfigurationError, FireflyFetchError


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
async def test_firefly_yield_transactions_raises_on_page_fetch_error() -> None:
    client = FireflyClient(base_url="http://test", token="token")

    page1_data = {
        "data": [{"id": "1", "attributes": {"transactions": [{"description": "t1"}]}}],
        "meta": {"pagination": {"total": 2, "total_pages": 2}},
    }

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client_cls.return_value = mock_client

        mock_resp1 = MagicMock()
        mock_resp1.json.return_value = page1_data
        mock_resp1.raise_for_status.return_value = None

        mock_client.get = AsyncMock(side_effect=[mock_resp1, RuntimeError("boom")])

        pages = []
        with pytest.raises(FireflyFetchError, match="page 2"):
            async for txs, meta in client.yield_transactions(limit_per_page=1):
                pages.append((txs, meta))

    assert len(pages) == 1
    assert pages[0][0][0]["id"] == "1"


@pytest.mark.anyio
async def test_firefly_get_transactions_requires_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FIREFLY_URL", raising=False)
    monkeypatch.delenv("FIREFLY_TOKEN", raising=False)
    client = FireflyClient(base_url=None, token=None)

    with pytest.raises(FireflyConfigurationError, match="FIREFLY_URL and FIREFLY_TOKEN"):
        await client.get_transactions()


@pytest.mark.anyio
async def test_firefly_yield_transactions_requires_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FIREFLY_URL", raising=False)
    monkeypatch.delenv("FIREFLY_TOKEN", raising=False)
    client = FireflyClient(base_url=None, token=None)

    with pytest.raises(FireflyConfigurationError, match="FIREFLY_URL and FIREFLY_TOKEN"):
        await client.yield_transactions().__anext__()


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
        client.refresh(base_url="http://test", token="token")
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


def test_firefly_refresh_updates_timeout_before_replacing_client() -> None:
    client = FireflyClient(
        base_url="http://test",
        token="token",
        http_timeout=10.0,
    )
    seen_timeouts: list[float] = []

    def fake_replace_client() -> None:
        seen_timeouts.append(client._http_timeout)  # noqa: SLF001

    client._replace_client = fake_replace_client  # type: ignore[method-assign]  # noqa: SLF001

    client.refresh(http_timeout=25.0)

    assert seen_timeouts == [25.0]
    assert client._http_timeout == 25.0  # noqa: SLF001


def test_firefly_replace_client_closes_synchronously_without_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FireflyClient(base_url="http://test", token="token")
    mock_http_client = MagicMock()
    mock_http_client.is_closed = False

    async def close_client() -> None:
        return None

    mock_http_client.aclose.return_value = close_client()
    client._client = mock_http_client  # noqa: SLF001

    monkeypatch.setattr(
        "firefly_categorizer.integration.firefly.asyncio.get_running_loop",
        MagicMock(side_effect=RuntimeError),
    )

    captured: dict[str, Any] = {}

    def fake_run(coro: Any) -> None:
        captured["coro"] = coro
        coro.close()

    monkeypatch.setattr("firefly_categorizer.integration.firefly.asyncio.run", fake_run)

    client._replace_client()  # noqa: SLF001

    assert client._client is None  # noqa: SLF001
    assert captured["coro"] is not None


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


@pytest.mark.anyio
async def test_train_bulk_propagates_firefly_page_fetch_errors() -> None:
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

    async def mock_generator(
        limit_per_page: int = 500
    ) -> AsyncGenerator[tuple[list[dict[str, Any]], dict[str, Any]], None]:
        yield batch1
        raise FireflyFetchError(2, RuntimeError("boom"))

    mock_firefly.yield_transactions.side_effect = mock_generator

    training_manager = TrainingManager(
        service=mock_service,
        firefly=mock_firefly,
        page_size=500,
    )

    with pytest.raises(FireflyFetchError, match="page 2"):
        await training_manager.train_bulk()

    assert mock_service.learn.call_count == 1


@pytest.mark.anyio
async def test_training_stream_continues_after_client_disconnect() -> None:
    """Disconnecting SSE client should not cancel the running training job."""
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
        limit_per_page: int = 500,
    ) -> AsyncGenerator[tuple[list[dict[str, Any]], dict[str, Any]], None]:
        yield batch1
        await asyncio.sleep(0)
        yield batch2

    mock_firefly.yield_transactions.side_effect = mock_generator

    training_manager = TrainingManager(
        service=mock_service,
        firefly=mock_firefly,
        page_size=500,
    )

    stream = training_manager.stream()
    first_event = await stream.__anext__()
    assert '"stage": "start"' in first_event
    await stream.aclose()

    for _ in range(200):
        status = training_manager.get_status()
        if status.get("stage") == "complete" and not status.get("active"):
            break
        await asyncio.sleep(0.01)

    status = training_manager.get_status()
    assert status["stage"] == "complete"
    assert status["trained"] == 2
    assert status["total_fetched"] == 2
    assert isinstance(status["avg_fetch_last_10_seconds"], float)
    assert isinstance(status["avg_train_last_10_seconds"], float)
    assert isinstance(status["avg_total_last_10_seconds"], float)
    assert status["avg_total_last_10_seconds"] >= 0
    assert status["avg_total_last_10_seconds"] == pytest.approx(
        status["avg_fetch_last_10_seconds"] + status["avg_train_last_10_seconds"],
    )
    assert training_manager.active is False
    assert mock_service.learn.call_count == 2


@pytest.mark.anyio
async def test_training_stream_reports_firefly_page_fetch_errors() -> None:
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

    async def mock_generator(
        limit_per_page: int = 500,
    ) -> AsyncGenerator[tuple[list[dict[str, Any]], dict[str, Any]], None]:
        yield batch1
        raise FireflyFetchError(2, RuntimeError("boom"))

    mock_firefly.yield_transactions.side_effect = mock_generator

    training_manager = TrainingManager(
        service=mock_service,
        firefly=mock_firefly,
        page_size=500,
    )

    stream = training_manager.stream()
    payloads = []
    for _ in range(4):
        event = await asyncio.wait_for(stream.__anext__(), timeout=1.0)
        payload = json.loads(event.removeprefix("data: ").strip())
        payloads.append(payload)
        if payload.get("stage") == "error":
            break

    await stream.aclose()

    assert payloads[-1]["stage"] == "error"
    assert "page 2" in payloads[-1]["message"]
    assert training_manager.get_status()["stage"] == "error"
    assert mock_service.learn.call_count == 1


@pytest.mark.anyio
async def test_training_stream_reports_missing_firefly_credentials() -> None:
    from firefly_categorizer.services.training import TrainingManager

    mock_firefly = MagicMock()
    mock_firefly.require_credentials.side_effect = FireflyConfigurationError(
        "Firefly API credentials are missing. Configure FIREFLY_URL and FIREFLY_TOKEN."
    )
    mock_service = MagicMock()

    training_manager = TrainingManager(
        service=mock_service,
        firefly=mock_firefly,
        page_size=500,
    )

    stream = training_manager.stream()
    event = await asyncio.wait_for(stream.__anext__(), timeout=1.0)
    payload = json.loads(event.removeprefix("data: ").strip())

    assert payload["stage"] == "error"
    assert payload["message"] == (
        "Firefly API credentials are missing. Configure FIREFLY_URL and FIREFLY_TOKEN."
    )

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(stream.__anext__(), timeout=1.0)


@pytest.mark.anyio
async def test_training_stream_can_resume_after_pause() -> None:
    """A paused training run should continue when a new stream connection starts."""
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
        limit_per_page: int = 500,
    ) -> AsyncGenerator[tuple[list[dict[str, Any]], dict[str, Any]], None]:
        yield batch1
        await asyncio.sleep(0.02)
        yield batch2

    mock_firefly.yield_transactions.side_effect = mock_generator

    training_manager = TrainingManager(
        service=mock_service,
        firefly=mock_firefly,
        page_size=500,
    )

    first_stream = training_manager.stream()
    _ = await first_stream.__anext__()
    _ = await first_stream.__anext__()
    assert training_manager.request_pause() is True
    paused_event = await first_stream.__anext__()
    paused_payload = json.loads(paused_event.removeprefix("data: ").strip())
    assert paused_payload["stage"] == "paused"
    await first_stream.aclose()

    second_stream = training_manager.stream()
    complete_seen = False
    first_resume_stage: str | None = None
    for _ in range(20):
        try:
            event = await asyncio.wait_for(second_stream.__anext__(), timeout=1.0)
        except StopAsyncIteration:
            break
        payload = json.loads(event.removeprefix("data: ").strip())
        if first_resume_stage is None:
            first_resume_stage = payload.get("stage")
        if payload.get("stage") == "complete":
            complete_seen = True
            break

    await second_stream.aclose()
    status = training_manager.get_status()
    assert first_resume_stage in {"start", "processing", "complete"}
    assert complete_seen
    assert status["stage"] == "complete"
    assert status["trained"] == 1
    assert mock_service.learn.call_count == 2


@pytest.mark.anyio
async def test_training_stream_emits_terminal_event_on_reset_cancel() -> None:
    """Resetting state during an active stream should not leave subscribers hanging."""
    from firefly_categorizer.services.training import TrainingManager

    mock_firefly = MagicMock()
    mock_service = MagicMock()

    async def mock_generator(
        limit_per_page: int = 500,
    ) -> AsyncGenerator[tuple[list[dict[str, Any]], dict[str, Any]], None]:
        await asyncio.sleep(10)
        yield [], {"total": 0}

    mock_firefly.yield_transactions.side_effect = mock_generator

    training_manager = TrainingManager(
        service=mock_service,
        firefly=mock_firefly,
        page_size=500,
    )

    stream = training_manager.stream()
    first_event = await asyncio.wait_for(stream.__anext__(), timeout=1.0)
    assert '"stage": "start"' in first_event

    training_manager.reset_state()

    terminal_event = await asyncio.wait_for(stream.__anext__(), timeout=1.0)
    payload = json.loads(terminal_event.removeprefix("data: ").strip())
    assert payload["stage"] == "error"
    assert "cancel" in payload["message"].lower()

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(stream.__anext__(), timeout=1.0)
