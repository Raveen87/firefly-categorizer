from collections.abc import Generator
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from firefly_categorizer.classifiers.llm import LLMClassifier
from firefly_categorizer.models import Transaction


@pytest.fixture
def mock_openai_client() -> Generator[MagicMock, None, None]:
    with patch("firefly_categorizer.classifiers.llm.OpenAI") as mock:
        yield mock

def test_llm_classify(mock_openai_client: MagicMock) -> None:
    # Setup mock response
    mock_instance = mock_openai_client.return_value
    mock_completion = MagicMock()
    mock_completion.choices[0].message.content = "Groceries"
    mock_instance.chat.completions.create.return_value = mock_completion

    classifier = LLMClassifier(api_key="sk-fake", model="gpt-4")
    t = Transaction(description="Whole Foods", amount=100.0, date=datetime.now())

    res = classifier.classify(t)

    assert res is not None
    assert res.category.name == "Groceries"
    assert res.source == "llm"

    # Verify call
    mock_instance.chat.completions.create.assert_called_once()
