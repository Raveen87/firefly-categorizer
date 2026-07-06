import asyncio
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from firefly_categorizer.api.routes import pages
from firefly_categorizer.integration.firefly import FireflyConfigurationError
from firefly_categorizer.main import app
from firefly_categorizer.models import CategorizationResult, Category
from firefly_categorizer.services.categorization import CategorizationPipeline

client = TestClient(app)

@pytest.fixture
def mock_firefly() -> Generator[AsyncMock, None, None]:
    had_firefly = hasattr(app.state, "firefly")
    original_firefly = getattr(app.state, "firefly", None)
    mock = AsyncMock()
    app.state.firefly = mock
    yield mock
    if had_firefly:
        app.state.firefly = original_firefly
    else:
        delattr(app.state, "firefly")

@pytest.fixture
def mock_service(mock_firefly: AsyncMock) -> Generator[MagicMock, None, None]:
    had_service = hasattr(app.state, "service")
    had_pipeline = hasattr(app.state, "pipeline")
    original_service = getattr(app.state, "service", None)
    original_pipeline = getattr(app.state, "pipeline", None)
    mock = MagicMock()
    app.state.service = mock
    app.state.pipeline = CategorizationPipeline(service=mock, firefly=mock_firefly)
    yield mock
    if had_service:
        app.state.service = original_service
    else:
        delattr(app.state, "service")
    if had_pipeline:
        app.state.pipeline = original_pipeline
    else:
        delattr(app.state, "pipeline")


@pytest.fixture
def mock_training_manager() -> Generator[MagicMock, None, None]:
    had_training_manager = hasattr(app.state, "training_manager")
    original_training_manager = getattr(app.state, "training_manager", None)
    mock = MagicMock()
    mock.train_bulk = AsyncMock()
    app.state.training_manager = mock
    yield mock
    if had_training_manager:
        app.state.training_manager = original_training_manager
    else:
        delattr(app.state, "training_manager")


def test_get_transactions_no_predict(mock_firefly: AsyncMock, mock_service: MagicMock) -> None:
    # Mock Firefly returning uncategorized transactions
    mock_firefly.get_categories.return_value = []
    mock_firefly.get_transactions.return_value = {
        "data": [
            {
                "id": "1",
                "attributes": {
                    "transactions": [{
                        "description": "uncategorized tx",
                        "amount": "10.00",
                        "date": "2023-01-01T10:00:00Z",
                        "category_name": None
                    }]
                }
            }
        ],
        "meta": {"total": 1}
    }

    response = client.get("/api/transactions")
    assert response.status_code == 200
    data = response.json()
    assert "transactions" in data
    assert len(data["transactions"]) == 1
    # Should not have called categorize
    mock_service.categorize.assert_not_called()
    assert data["transactions"][0]["prediction"] is None

def test_get_transactions_with_predict(
    mock_firefly: AsyncMock,
    mock_service: MagicMock,
    monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTO_APPROVE_THRESHOLD", "0")
    # Mock Firefly returning uncategorized transactions
    mock_firefly.get_categories.return_value = [{"attributes": {"name": "Food"}}]
    mock_firefly.get_transactions.return_value = {
        "data": [
            {
                "id": "1",
                "attributes": {
                    "transactions": [{
                        "description": "uncategorized tx",
                        "amount": "10.00",
                        "date": "2023-01-01T10:00:00Z",
                        "category_name": None
                    }]
                }
            }
        ],
        "meta": {"total": 1}
    }

    # Mock prediction
    mock_service.categorize.return_value = CategorizationResult(
        category=Category(name="Food"),
        confidence=0.9,
        source="mock"
    )

    response = client.get("/api/transactions?predict=true")
    assert response.status_code == 200
    data = response.json()
    assert len(data["transactions"]) == 1

    # Should have called categorize
    mock_service.categorize.assert_called_once()
    assert data["transactions"][0]["prediction"] is not None
    assert data["transactions"][0]["prediction"]["category"]["name"] == "Food"


def test_get_transactions_with_invalid_auto_approve_threshold(
    mock_firefly: AsyncMock,
    mock_service: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTO_APPROVE_THRESHOLD", "not-a-number")
    mock_firefly.get_categories.return_value = [{"attributes": {"name": "Food"}}]
    mock_firefly.get_transactions.return_value = {
        "data": [
            {
                "id": "1",
                "attributes": {
                    "transactions": [{
                        "description": "uncategorized tx",
                        "amount": "10.00",
                        "date": "2023-01-01T10:00:00Z",
                        "category_name": None
                    }]
                }
            }
        ],
        "meta": {"total": 1}
    }
    mock_service.categorize.return_value = CategorizationResult(
        category=Category(name="Food"),
        confidence=0.9,
        source="mock",
    )

    response = client.get("/api/transactions?predict=true")

    assert response.status_code == 200
    data = response.json()
    assert len(data["transactions"]) == 1
    assert data["transactions"][0]["prediction"] is not None


def test_get_transactions_empty_categories_block_auto_approve(
    mock_firefly: AsyncMock,
    mock_service: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTO_APPROVE_THRESHOLD", "0.5")
    mock_firefly.get_categories.return_value = []
    mock_firefly.update_transaction.return_value = True
    mock_firefly.get_transactions.return_value = {
        "data": [
            {
                "id": "1",
                "attributes": {
                    "transactions": [{
                        "description": "uncategorized tx",
                        "amount": "10.00",
                        "date": "2023-01-01T10:00:00Z",
                        "category_name": None
                    }]
                }
            }
        ],
        "meta": {"total": 1}
    }

    def categorize_with_constraints(
        _transaction: Any,
        valid_categories: list[str] | None = None,
    ) -> CategorizationResult | None:
        if valid_categories is not None and not valid_categories:
            return None
        return CategorizationResult(
            category=Category(name="StaleCategory"),
            confidence=1.0,
            source="mock",
        )

    mock_service.categorize.side_effect = categorize_with_constraints

    response = client.get("/api/transactions?predict=true")

    assert response.status_code == 200
    data = response.json()
    assert len(data["transactions"]) == 1
    assert data["transactions"][0]["prediction"] is None
    assert data["transactions"][0]["auto_approved"] is False
    assert mock_service.categorize.call_args.kwargs["valid_categories"] == []
    mock_firefly.update_transaction.assert_not_called()
    mock_service.learn.assert_not_called()


def test_categorize_stream_empty_categories_block_auto_approve(
    mock_firefly: AsyncMock,
    mock_service: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTO_APPROVE_THRESHOLD", "0.5")
    mock_firefly.get_categories.return_value = []
    mock_firefly.update_transaction.return_value = True
    mock_firefly.get_transactions.return_value = {
        "data": [
            {
                "id": "1",
                "attributes": {
                    "transactions": [{
                        "description": "uncategorized tx",
                        "amount": "10.00",
                        "date": "2023-01-01T10:00:00Z",
                        "category_name": None
                    }]
                }
            }
        ],
        "meta": {"total": 1}
    }

    def categorize_with_constraints(
        _transaction: Any,
        valid_categories: list[str] | None = None,
    ) -> CategorizationResult | None:
        if valid_categories is not None and not valid_categories:
            return None
        return CategorizationResult(
            category=Category(name="StaleCategory"),
            confidence=1.0,
            source="mock",
        )

    mock_service.categorize.side_effect = categorize_with_constraints

    response = client.get("/api/categorize-stream")

    assert response.status_code == 200
    assert '"auto_approved": false' in response.text
    assert '"prediction": null' in response.text
    assert mock_service.categorize.call_args.kwargs["valid_categories"] == []
    mock_firefly.update_transaction.assert_not_called()
    mock_service.learn.assert_not_called()


def test_get_transactions_missing_firefly_credentials(mock_firefly: AsyncMock) -> None:
    mock_firefly.get_categories.side_effect = FireflyConfigurationError(
        "Firefly API credentials are missing. Configure FIREFLY_URL and FIREFLY_TOKEN."
    )

    response = client.get("/api/transactions")

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Firefly API credentials are missing. Configure FIREFLY_URL and FIREFLY_TOKEN."
    )


def test_categorize_missing_firefly_credentials(
    mock_firefly: AsyncMock,
    mock_service: MagicMock,
) -> None:
    mock_firefly.get_categories.side_effect = FireflyConfigurationError(
        "Firefly API credentials are missing. Configure FIREFLY_URL and FIREFLY_TOKEN."
    )

    response = client.post(
        "/categorize",
        json={
            "transaction": {
                "description": "coffee",
                "amount": 12.5,
                "date": "2023-01-01T10:00:00Z",
                "currency": "EUR",
            }
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Firefly API credentials are missing. Configure FIREFLY_URL and FIREFLY_TOKEN."
    )
    mock_service.categorize.assert_not_called()


def test_webhook_empty_categories_block_auto_approve(
    mock_firefly: AsyncMock,
    mock_service: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTO_APPROVE_THRESHOLD", "0.5")
    mock_firefly.get_categories.return_value = []
    mock_firefly.update_transaction.return_value = True

    def categorize_with_constraints(
        _transaction: Any,
        valid_categories: list[str] | None = None,
    ) -> CategorizationResult | None:
        if valid_categories is not None and not valid_categories:
            return None
        return CategorizationResult(
            category=Category(name="StaleCategory"),
            confidence=1.0,
            source="mock",
        )

    mock_service.categorize.side_effect = categorize_with_constraints

    response = client.post(
        "/webhook/firefly",
        json={
            "event": "transaction_created",
            "data": {
                "id": "tx-1",
                "attributes": {
                    "transactions": [
                        {
                            "description": "uncategorized tx",
                            "amount": "10.00",
                            "date": "2023-01-01T10:00:00Z",
                            "category_name": None,
                        }
                    ],
                },
            },
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored", "reason": "no prediction"}
    assert mock_service.categorize.call_args.kwargs["valid_categories"] == []
    mock_firefly.update_transaction.assert_not_called()
    mock_service.learn.assert_not_called()


def test_get_categories(mock_firefly: AsyncMock) -> None:
    mock_firefly.get_categories.return_value = [
        {"attributes": {"name": "Food"}},
        {"attributes": {"name": "Rent"}}
    ]

    response = client.get("/api/categories")
    assert response.status_code == 200
    assert response.json() == ["Food", "Rent"]

def test_get_categories_error(mock_firefly: AsyncMock) -> None:
    mock_firefly.get_categories.side_effect = Exception("Firefly error")

    response = client.get("/api/categories")
    assert response.status_code == 502
    assert "Firefly error" in response.json()["detail"]


def test_get_categories_missing_firefly_credentials(mock_firefly: AsyncMock) -> None:
    mock_firefly.get_categories.side_effect = FireflyConfigurationError(
        "Firefly API credentials are missing. Configure FIREFLY_URL and FIREFLY_TOKEN."
    )

    response = client.get("/api/categories")

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Firefly API credentials are missing. Configure FIREFLY_URL and FIREFLY_TOKEN."
    )


def test_train_models_missing_firefly_credentials(mock_training_manager: MagicMock) -> None:
    mock_training_manager.train_bulk.side_effect = FireflyConfigurationError(
        "Firefly API credentials are missing. Configure FIREFLY_URL and FIREFLY_TOKEN."
    )

    response = client.post("/train")

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Firefly API credentials are missing. Configure FIREFLY_URL and FIREFLY_TOKEN."
    )


def test_learn_transaction_missing_firefly_credentials(
    mock_firefly: AsyncMock,
    mock_service: MagicMock,
) -> None:
    mock_firefly.require_credentials = MagicMock(
        side_effect=FireflyConfigurationError(
            "Firefly API credentials are missing. Configure FIREFLY_URL and FIREFLY_TOKEN."
        )
    )

    response = client.post(
        "/learn",
        json={
            "transaction": {
                "description": "coffee",
                "amount": 12.5,
                "date": "2023-01-01T10:00:00Z",
                "currency": "EUR",
            },
            "category": {"name": "Food"},
            "transaction_id": "tx-1",
            "existing_tags": [],
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Firefly API credentials are missing. Configure FIREFLY_URL and FIREFLY_TOKEN."
    )
    mock_service.learn.assert_not_called()


def test_learn_transaction_rejects_failed_firefly_update(
    mock_firefly: AsyncMock,
    mock_service: MagicMock,
) -> None:
    mock_firefly.require_credentials = MagicMock(return_value=None)
    mock_firefly.update_transaction.return_value = False

    response = client.post(
        "/learn",
        json={
            "transaction": {
                "description": "coffee",
                "amount": 12.5,
                "date": "2023-01-01T10:00:00Z",
                "currency": "EUR",
            },
            "category": {"name": "Food"},
            "transaction_id": "tx-1",
            "existing_tags": [],
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"] == (
        "Firefly rejected the category update. The transaction was not saved."
    )
    mock_service.learn.assert_not_called()


def test_get_categories_no_firefly() -> None:
    had_firefly = hasattr(app.state, "firefly")
    original_firefly = getattr(app.state, "firefly", None)
    # Ensure firefly is NOT in app.state
    if had_firefly:
        delattr(app.state, "firefly")

    try:
        response = client.get("/api/categories")
        assert response.status_code == 200
        assert response.json() == []
    finally:
        if had_firefly:
            app.state.firefly = original_firefly

def test_get_categories_empty(mock_firefly: AsyncMock) -> None:
    mock_firefly.get_categories.return_value = []

    response = client.get("/api/categories")
    assert response.status_code == 200
    assert response.json() == []


def test_save_config_accepts_form_post(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_payload: dict[str, str] = {}

    def fake_apply_config_updates(payload: dict[str, str]) -> tuple[dict[str, str], dict[str, Any]]:
        nonlocal captured_payload
        captured_payload = payload
        return {}, {"OPENAI_MODEL": payload["OPENAI_MODEL"]}

    def fake_apply_runtime_updates(_app: Any, updates: dict[str, Any]) -> None:
        assert updates == {"OPENAI_MODEL": "gpt-4o-mini"}

    monkeypatch.setattr(
        "firefly_categorizer.api.routes.pages.configuration.apply_config_updates",
        fake_apply_config_updates,
    )
    monkeypatch.setattr(
        "firefly_categorizer.api.routes.pages.configuration.apply_runtime_updates",
        fake_apply_runtime_updates,
    )

    response = client.post(
        "/config",
        data={"OPENAI_MODEL": "gpt-4o-mini"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/config?saved=1"
    assert captured_payload == {"OPENAI_MODEL": "gpt-4o-mini"}


def test_training_page_defaults_to_start_training_label() -> None:
    response = client.get("/train")
    assert response.status_code == 200
    assert "Start Training" in response.text


def test_pages_routes_fall_back_to_legacy_template_response_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_template_response(*args: Any, **kwargs: Any) -> dict[str, Any]:
        if kwargs:
            raise TypeError("TemplateResponse() got an unexpected keyword argument 'request'")

        name, context = args
        calls.append((name, context))
        return {"name": name, "context": context}

    monkeypatch.setattr(
        "firefly_categorizer.api.routes.pages.templates.TemplateResponse",
        fake_template_response,
    )
    monkeypatch.setattr(
        "firefly_categorizer.api.routes.pages.configuration.build_config_context",
        lambda field_errors=None: {"field_errors": field_errors},
    )
    monkeypatch.setattr(
        "firefly_categorizer.api.routes.pages.configuration.apply_config_updates",
        lambda _payload: ({"OPENAI_MODEL": "Required"}, {}),
    )

    request = MagicMock()
    request.form = AsyncMock(return_value={"OPENAI_MODEL": ""})

    index_response = asyncio.run(
        pages.index(
            request=request,
            firefly=None,
            start_date="2024-01-01",
            end_date="2024-01-31",
            scope=None,
        )
    )
    help_response = asyncio.run(pages.help_page(request))
    train_response = asyncio.run(pages.train_page(request))
    config_response = asyncio.run(pages.config_page(request, saved=True))
    invalid_config_response = asyncio.run(pages.save_config(request))

    assert index_response["name"] == "index.html"
    assert index_response["context"]["request"] is request
    assert index_response["context"]["scope"] == "range"
    assert help_response["name"] == "help.html"
    assert help_response["context"]["request"] is request
    assert train_response["name"] == "train.html"
    assert train_response["context"]["request"] is request
    assert config_response["name"] == "config.html"
    assert config_response["context"]["status"] == "Configuration saved."
    assert invalid_config_response["name"] == "config.html"
    assert invalid_config_response["context"]["errors"] == {"OPENAI_MODEL": "Required"}
    assert [name for name, _context in calls] == [
        "index.html",
        "help.html",
        "train.html",
        "config.html",
        "config.html",
    ]
