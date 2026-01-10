from datetime import datetime

import pytest

from firefly_categorizer.classifiers.memory import MemoryMatcher
from firefly_categorizer.models import Category, Transaction


@pytest.fixture
def memory_matcher(tmp_path):
    data_file = tmp_path / "memory.json"
    return MemoryMatcher(data_path=str(data_file), threshold=50.0)

def test_memory_learn_and_exact_match(memory_matcher):
    t1 = Transaction(description="Spotify Premium", amount=10.99, date=datetime.now())
    c1 = Category(name="Subscriptions")

    memory_matcher.learn(t1, c1)

    # Reload to verify persistence
    memory_matcher.load()

    res = memory_matcher.classify(t1)
    assert res is not None
    assert res.category.name == "Subscriptions"
    assert res.confidence == 1.0
    assert res.source == "memory_exact"

def test_memory_fuzzy_match(memory_matcher):
    t1 = Transaction(description="Uber Ride", amount=15.50, date=datetime.now())
    c1 = Category(name="Transport")
    memory_matcher.learn(t1, c1)

    # Slightly different description
    t2 = Transaction(description="Uber Ride XL", amount=15.50, date=datetime.now())

    res = memory_matcher.classify(t2)
    assert res is not None
    assert res.category.name == "Transport"
    assert res.confidence > 0.4
    assert res.source == "memory_fuzzy"

def test_memory_no_match(memory_matcher):
    t1 = Transaction(description="Unknown Transaction", amount=100.0, date=datetime.now())
    res = memory_matcher.classify(t1)
    assert res is None
