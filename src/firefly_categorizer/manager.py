from typing import Optional, List
from firefly_categorizer.models import Transaction, CategorizationResult, Category
from classifiers.base import Classifier
from classifiers.memory import MemoryMatcher
from classifiers.tfidf import TfidfClassifier
from classifiers.llm import LLMClassifier
import os

class CategorizerService:
    def __init__(self, 
                 memory_threshold: float = 90.0,
                 tfidf_threshold: float = 0.5,
                 data_dir: str = "."):
        
        self.classifiers: List[Classifier] = []
        
        # 1. Memory Matcher (Highest priority)
        self.memory = MemoryMatcher(
            data_path=os.path.join(data_dir, "memory.json"),
            threshold=memory_threshold
        )
        self.classifiers.append(self.memory)
        
        # 2. TF-IDF Classifier
        self.tfidf = TfidfClassifier(
            data_path=os.path.join(data_dir, "tfidf.pkl"),
            threshold=tfidf_threshold
        )
        self.classifiers.append(self.tfidf)
        
        # 3. LLM Classifier (Fallback)
        # Only add if API key is present
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            self.llm = LLMClassifier(api_key=api_key)
            self.classifiers.append(self.llm)
        else:
            self.llm = None
            print("Warning: OPENAI_API_KEY not found. LLM classifier disabled.")

    def categorize(self, transaction: Transaction) -> Optional[CategorizationResult]:
        for classifier in self.classifiers:
            result = classifier.classify(transaction)
            if result:
                return result
        return None

    def learn(self, transaction: Transaction, category: Category):
        """
        Teach all trainable classifiers.
        """
        # We update Memory and TF-IDF. LLM usually isn't updated this way (RAG/Fine-tuning is complex).
        self.memory.learn(transaction, category)
        self.tfidf.learn(transaction, category)
