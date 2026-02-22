import asyncio
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from firefly_categorizer.api.routes import pages
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
