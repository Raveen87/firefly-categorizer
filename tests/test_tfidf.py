from datetime import datetime
from pathlib import Path

import pytest

from firefly_categorizer.classifiers.tfidf import TfidfClassifier
from firefly_categorizer.models import Category, Transaction


@pytest.fixture
def tfidf_classifier(tmp_path: Path) -> TfidfClassifier:
    data_file = tmp_path / "tfidf.pkl"
    return TfidfClassifier(data_path=str(data_file), threshold=0.5)

def test_tfidf_learn_and_classify(tfidf_classifier: TfidfClassifier) -> None:
    # Train heavily to ensure TF-IDF picks it up
    c1 = Category(name="Food")
    c2 = Category(name="Transport")
    transactions = [
        ("McDonalds", c1),
        ("Burger King", c1),
        ("Grocery Store", c1),
        ("Uber", c2),
        ("Lyft", c2),
    ]

    for desc, cat in transactions:
        t = Transaction(description=desc, amount=10.0, date=datetime.now())
        tfidf_classifier.learn(t, cat)

    # Test
    t_test = Transaction(description="McDonalds Drive Thru", amount=15.0, date=datetime.now())
    res = tfidf_classifier.classify(t_test)

    # Ideally it should match "Food"
    # Note: Tfidf with few samples can be flaky, but "McDonalds" word overlap should trigger it.
    assert res is not None
    assert res.category.name == "Food"
    assert res.source == "tfidf"

def test_tfidf_persistence(tfidf_classifier: TfidfClassifier, tmp_path: Path) -> None:
    t = Transaction(description="Netflix", amount=10.0, date=datetime.now())
    c = Category(name="Subscriptions")
    tfidf_classifier.learn(t, c)

    t2 = Transaction(description="Salary", amount=1000.0, date=datetime.now())
    c2 = Category(name="Income")
    tfidf_classifier.learn(t2, c2)

    # Create new instance pointing to same file
    data_file = tmp_path / "tfidf.pkl"
    new_classifier = TfidfClassifier(data_path=str(data_file))

    assert new_classifier.is_fitted
    assert len(new_classifier.examples) == 2
