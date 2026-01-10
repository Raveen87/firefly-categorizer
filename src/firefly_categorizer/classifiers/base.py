from abc import ABC, abstractmethod
from typing import List, Optional

from firefly_categorizer.models import CategorizationResult, Category, Transaction


class Classifier(ABC):
    @abstractmethod
    def classify(self, transaction: Transaction, valid_categories: Optional[List[str]] = None) -> Optional[CategorizationResult]:
        """Attempt to categorize the transaction."""
        pass

    @abstractmethod
    def learn(self, transaction: Transaction, category: Category):
        """Learn from a new transaction-category pair."""
        pass
