import threading
import time
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from firefly_categorizer.manager import CategorizerService
from firefly_categorizer.models import CategorizationResult, Category, Transaction


@pytest.fixture
def mock_classifiers() -> Generator[tuple[MagicMock, MagicMock, MagicMock], None, None]:
    with patch("firefly_categorizer.manager.MemoryMatcher") as mock_mem, \
         patch("firefly_categorizer.manager.TfidfClassifier") as mock_tfidf, \
         patch("firefly_categorizer.manager.LLMClassifier") as mock_llm, \
         patch("os.getenv", return_value="fake-key"):

        yield mock_mem, mock_tfidf, mock_llm

def test_manager_orchestration_priority(mock_classifiers: tuple[MagicMock, MagicMock, MagicMock]) -> None:
    mock_mem_cls, mock_tfidf_cls, mock_llm_cls = mock_classifiers

    # Setup instances
    mem_instance = mock_mem_cls.return_value
    tfidf_instance = mock_tfidf_cls.return_value
    llm_instance = mock_llm_cls.return_value

    service = CategorizerService(data_dir=".")

    t = Transaction(description="Test", amount=10.0, date=datetime.now())

    # Case 1: Memory matches
    mem_instance.classify.return_value = CategorizationResult(
        category=Category(name="MemoryCat"), confidence=1.0, source="memory"
    )
    res = service.categorize(t)
    assert res is not None
    assert res.category.name == "MemoryCat"
    assert res.source == "memory"
    tfidf_instance.classify.assert_not_called()

    # Case 2: Memory fails, TF-IDF matches
    mem_instance.classify.return_value = None
    tfidf_instance.classify.return_value = CategorizationResult(
        category=Category(name="TfidfCat"), confidence=0.8, source="tfidf"
    )
    res = service.categorize(t)
    assert res is not None
    assert res.category.name == "TfidfCat"
    assert res.source == "tfidf"
    llm_instance.classify.assert_not_called()

    # Case 3: Both fail, LLM matches
    tfidf_instance.classify.return_value = None
    llm_instance.classify.return_value = CategorizationResult(
        category=Category(name="LLMCat"), confidence=0.9, source="llm"
    )
    res = service.categorize(t)
    assert res is not None
    assert res.category.name == "LLMCat"
    assert res.source == "llm"


def test_learn_serializes_classifier_updates(mock_classifiers: tuple[MagicMock, MagicMock, MagicMock]) -> None:
    service = CategorizerService(data_dir=".")
    active_learns = 0
    max_active_learns = 0
    counter_lock = threading.Lock()

    def slow_memory_learn(transaction: Transaction, category: Category) -> None:
        nonlocal active_learns, max_active_learns
        with counter_lock:
            active_learns += 1
            max_active_learns = max(max_active_learns, active_learns)
        time.sleep(0.005)
        with counter_lock:
            active_learns -= 1

    service.memory.learn.side_effect = slow_memory_learn

    def learn_one(index: int) -> None:
        service.learn(
            Transaction(description=f"Transaction {index}", amount=1.0, date=datetime.now()),
            Category(name=f"Category {index % 2}"),
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(learn_one, range(12)))

    assert max_active_learns == 1
