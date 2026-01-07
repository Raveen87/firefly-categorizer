from abc import ABC, abstractmethod
from typing import Optional
from firefly_categorizer.models import Transaction, CategorizationResult, Category

class Classifier(ABC):
    @abstractmethod
    def classify(self, transaction: Transaction) -> Optional[CategorizationResult]:
        """Attempt to categorize the transaction."""
        pass

    @abstractmethod
    def learn(self, transaction: Transaction, category: Category):
        """Learn from a new transaction-category pair."""
        pass
