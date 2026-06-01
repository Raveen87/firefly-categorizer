import json
import os
import tempfile
import threading
from contextlib import suppress

from rapidfuzz import fuzz, process

from firefly_categorizer.models import CategorizationResult, Category, Transaction

from .base import Classifier


class MemoryMatcher(Classifier):
    def __init__(self, data_path: str = "memory.json", threshold: float = 90.0):
        self.data_path = data_path
        self.threshold = threshold
        self._lock = threading.RLock()
        self.memory: dict[str, str] = {} # description -> category_name
        self.load()

    def load(self) -> None:
        with self._lock:
            if os.path.exists(self.data_path):
                try:
                    with open(self.data_path) as f:
                        self.memory = json.load(f)
                except json.JSONDecodeError:
                    self.memory = {}

    def save(self) -> None:
        with self._lock:
            directory = os.path.dirname(os.path.abspath(self.data_path))
            os.makedirs(directory, exist_ok=True)
            fd, temp_path = tempfile.mkstemp(
                prefix=f".{os.path.basename(self.data_path)}.",
                suffix=".tmp",
                dir=directory,
            )
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(self.memory, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp_path, self.data_path)
            except Exception:
                with suppress(FileNotFoundError):
                    os.unlink(temp_path)
                raise

    def classify(
        self, transaction: Transaction, valid_categories: list[str] | None = None
    ) -> CategorizationResult | None:
        with self._lock:
            memory = dict(self.memory)

        if not memory:
            return None

        # Helper to check validity
        def is_valid(cat_name: str) -> bool:
            if valid_categories is None:
                return True
            return cat_name in valid_categories

        # 1. Exact match
        if transaction.description in memory:
            category_name = memory[transaction.description]
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
            memory.keys(),
            scorer=fuzz.token_sort_ratio
        )

        if result:
            match_description, score, _ = result
            if score >= self.threshold:
                category_name = memory[match_description]
                if is_valid(category_name):
                    return CategorizationResult(
                        category=Category(name=category_name),
                        confidence=score / 100.0,
                        source="memory_fuzzy"
                    )

        return None

    def learn(self, transaction: Transaction, category: Category) -> None:
        with self._lock:
            self.memory[transaction.description] = category.name
            self.save()

    def clear(self) -> None:
        with self._lock:
            self.memory = {}
            self.save()
