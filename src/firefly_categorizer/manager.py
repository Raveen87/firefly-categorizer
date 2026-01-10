import os

from firefly_categorizer.classifiers.base import Classifier
from firefly_categorizer.classifiers.llm import LLMClassifier
from firefly_categorizer.classifiers.memory import MemoryMatcher
from firefly_categorizer.classifiers.tfidf import TfidfClassifier
from firefly_categorizer.logger import get_logger
from firefly_categorizer.models import CategorizationResult, Category, Transaction

logger = get_logger(__name__)

class CategorizerService:
    def __init__(self,
                 memory_threshold: float = 90.0,
                 tfidf_threshold: float = 0.5,
                 data_dir: str = "."):

        self.classifiers: list[Classifier] = []

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
            logger.info(f"LLM Classifier enabled: model={model}, base_url={base_url or 'default'}")
        else:
            self.llm = None
            logger.warning("OPENAI_API_KEY not found. LLM classifier disabled.")

    def categorize(
        self, transaction: Transaction, valid_categories: list[str] | None = None
    ) -> CategorizationResult | None:
        for classifier in self.classifiers:
            classifier_name = classifier.__class__.__name__
            logger.debug(f"Trying {classifier_name} for: '{transaction.description[:50]}...'")

            result = classifier.classify(transaction, valid_categories=valid_categories)

            if result:
                logger.debug(
                    f"{classifier_name} returned: '{result.category.name}' "
                    f"(confidence: {result.confidence:.2f})"
                )
                return result
            else:
                logger.debug(f"{classifier_name} returned: None")

        logger.debug(f"No classifier matched for: '{transaction.description[:50]}...'")
        return None

    def learn(self, transaction: Transaction, category: Category) -> None:
        """
        Teach all trainable classifiers.
        """
        # We update Memory and TF-IDF. LLM usually isn't updated this way (RAG/Fine-tuning is complex).
        self.memory.learn(transaction, category)
        self.tfidf.learn(transaction, category)

    def clear_models(self) -> None:
        """
        Clear all local training data.
        """
        self.memory.clear()
        self.tfidf.clear()
        logger.info("All models cleared.")
