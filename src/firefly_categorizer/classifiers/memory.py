import json
import os
from typing import Optional, Dict, List
from rapidfuzz import process, fuzz
from firefly_categorizer.models import Transaction, CategorizationResult, Category
from .base import Classifier

class MemoryMatcher(Classifier):
    def __init__(self, data_path: str = "memory.json", threshold: float = 90.0):
        self.data_path = data_path
        self.threshold = threshold
        self.memory: Dict[str, str] = {} # description -> category_name
        self.load()

    def load(self):
        if os.path.exists(self.data_path):
            try:
                with open(self.data_path, "r") as f:
                    self.memory = json.load(f)
            except json.JSONDecodeError:
                self.memory = {}

    def save(self):
        with open(self.data_path, "w") as f:
            json.dump(self.memory, f, indent=2)

    def classify(self, transaction: Transaction, valid_categories: Optional[List[str]] = None) -> Optional[CategorizationResult]:
        if not self.memory:
            return None

        # Helper to check validity
        def is_valid(cat_name):
            if valid_categories is None:
                return True
            return cat_name in valid_categories

        # 1. Exact match
        if transaction.description in self.memory:
            category_name = self.memory[transaction.description]
            if is_valid(category_name):
                return CategorizationResult(
                    category=Category(name=category_name),
                    confidence=1.0,
                    source="memory_exact"
                )

        # 2. Fuzzy match
        # Extract best match from memory keys
        result = process.extractOne(
            transaction.description,
            self.memory.keys(),
            scorer=fuzz.token_sort_ratio
        )
        
        if result:
            match_description, score, _ = result
            if score >= self.threshold:
                category_name = self.memory[match_description]
                if is_valid(category_name):
                    return CategorizationResult(
                        category=Category(name=category_name),
                        confidence=score / 100.0,
                        source="memory_fuzzy"
                    )

        return None

    def learn(self, transaction: Transaction, category: Category):
        self.memory[transaction.description] = category.name
        self.save()

    def clear(self):
        self.memory = {}
        self.save()
