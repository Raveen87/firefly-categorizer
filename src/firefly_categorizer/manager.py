from typing import Optional, List
from firefly_categorizer.models import Transaction, CategorizationResult, Category
from firefly_categorizer.classifiers.base import Classifier
from firefly_categorizer.classifiers.memory import MemoryMatcher
from firefly_categorizer.classifiers.tfidf import TfidfClassifier
from firefly_categorizer.classifiers.llm import LLMClassifier
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
            model = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
            base_url = os.getenv("OPENAI_BASE_URL")
            self.llm = LLMClassifier(api_key=api_key, model=model, base_url=base_url)
            self.classifiers.append(self.llm)
            print(f"LLM Classifier enabled: model={model}, base_url={base_url or 'default'}")
        else:
            self.llm = None
            print("Warning: OPENAI_API_KEY not found. LLM classifier disabled.")

    def categorize(self, transaction: Transaction, valid_categories: Optional[List[str]] = None) -> Optional[CategorizationResult]:
        for classifier in self.classifiers:
            classifier_name = classifier.__class__.__name__
            print(f"[DEBUG] Trying {classifier_name} for: '{transaction.description[:50]}...'")
            
            result = classifier.classify(transaction, valid_categories=valid_categories)
            
            if result:
                print(f"[DEBUG] {classifier_name} returned: '{result.category.name}' (confidence: {result.confidence:.2f})")
                return result
            else:
                print(f"[DEBUG] {classifier_name} returned: None")
        
        print(f"[DEBUG] No classifier matched for: '{transaction.description[:50]}...'")
        return None

    def learn(self, transaction: Transaction, category: Category):
        """
        Teach all trainable classifiers.
        """
        # We update Memory and TF-IDF. LLM usually isn't updated this way (RAG/Fine-tuning is complex).
        self.memory.learn(transaction, category)
        self.tfidf.learn(transaction, category)

    def clear_models(self):
        """
        Clear all local training data.
        """
        self.memory.clear()
        self.tfidf.clear()
        print("[MANAGER] All models cleared.")
