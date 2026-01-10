from abc import ABC, abstractmethod

from firefly_categorizer.models import CategorizationResult, Category, Transaction


class Classifier(ABC):
    @abstractmethod
    def classify(
        self, transaction: Transaction, valid_categories: list[str] | None = None
    ) -> CategorizationResult | None:
        """Attempt to categorize the transaction."""
        pass

    @abstractmethod
    def learn(self, transaction: Transaction, category: Category) -> None:
        """Learn from a new transaction-category pair."""
        pass
