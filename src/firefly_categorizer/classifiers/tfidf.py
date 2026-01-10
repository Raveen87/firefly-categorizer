import os
import pickle

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import SGDClassifier
from sklearn.pipeline import Pipeline

from firefly_categorizer.models import CategorizationResult, Category, Transaction

from .base import Classifier


class TfidfClassifier(Classifier):
    def __init__(self, data_path: str = "tfidf_model.pkl", threshold: float = 0.5):
        self.data_path = data_path
        self.threshold = threshold
        self.pipeline = Pipeline([
            ('tfidf', TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5), min_df=1)),
            ('clf', SGDClassifier(loss='log_loss', random_state=42))
        ])
        self.examples: list[str] = []
        self.labels: list[str] = []
        self.is_fitted = False
        self.load()

    def load(self) -> None:
        if os.path.exists(self.data_path):
            try:
                with open(self.data_path, "rb") as f:
                    data = pickle.load(f)
                    self.examples = data.get("examples", [])
                    self.labels = data.get("labels", [])
                    if self.examples:
                        self.pipeline.fit(self.examples, self.labels)
                        self.is_fitted = True
            except (pickle.UnpicklingError, EOFError):
                self.examples = []
                self.labels = []
                self.is_fitted = False

    def save(self) -> None:
        with open(self.data_path, "wb") as f:
            pickle.dump({
                "examples": self.examples,
                "labels": self.labels
            }, f)

    def classify(
        self, transaction: Transaction, valid_categories: list[str] | None = None
    ) -> CategorizationResult | None:
        if not self.is_fitted:
            return None

        try:
            probs = self.pipeline.predict_proba([transaction.description])[0]
            max_prob_idx = probs.argmax()
            confidence = probs[max_prob_idx]
            category_name = self.pipeline.classes_[max_prob_idx]

            if confidence >= self.threshold:
                if valid_categories is None or category_name in valid_categories:
                    return CategorizationResult(
                        category=Category(name=category_name),
                        confidence=float(confidence),
                        source="tfidf"
                    )
        except Exception:
            # Handle cases where vocabulary might not match, though Tfidf handles this gracefully mainly
            pass

        return None

    def learn(self, transaction: Transaction, category: Category) -> None:
        self.examples.append(transaction.description)
        self.labels.append(category.name)

        # In a real heavy production system, we wouldn't retrain on every single learn,
        # but for personal finance volume, this is fine and ensures immediate feedback.
        if len(set(self.labels)) >= 2:
            self.pipeline.fit(self.examples, self.labels)
            self.is_fitted = True
            self.save()

    def clear(self) -> None:
        self.examples = []
        self.labels = []
        self.is_fitted = False
        self.pipeline = Pipeline([
            ('tfidf', TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5), min_df=1)),
            ('clf', SGDClassifier(loss='log_loss', random_state=42))
        ])
        self.save()
