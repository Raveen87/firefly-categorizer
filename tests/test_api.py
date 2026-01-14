from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

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
