import os
from typing import Optional, List
from openai import OpenAI
from firefly_categorizer.models import Transaction, CategorizationResult, Category
from .base import Classifier
from firefly_categorizer.logger import get_logger

logger = get_logger(__name__)

class LLMClassifier(Classifier):
    def __init__(self, api_key: str = None, model: str = "gpt-3.5-turbo", base_url: str = None):
        self.client = OpenAI(
            api_key=api_key or os.getenv("OPENAI_API_KEY"),
            base_url=base_url or os.getenv("OPENAI_BASE_URL") or None
        )
        self.model = model

    def classify(self, transaction: Transaction, valid_categories: Optional[List[str]] = None) -> Optional[CategorizationResult]:
        try:
            prompt_categories = ""
            if valid_categories:
                cats_str = ", ".join(valid_categories)
                prompt_categories = f"\nUse ONLY one of the following categories: {cats_str}"

            prompt = f"""
            Categorize this financial transaction into a standard personal finance category.
            Transaction: {transaction.description}
            Amount: {transaction.amount} {transaction.currency}
            Date: {transaction.date}
            {prompt_categories}
            
            Return ONLY the category name. If unsure or if it doesn't fit any valid category, return 'Uncategorized'.
            """
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a helpful financial assistant."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0
            )
            
            category_name = response.choices[0].message.content.strip()

            if valid_categories:
                if category_name not in valid_categories:
                    return None
            
            # Simple heuristic for confidence (LLMs are usually confident)
            return CategorizationResult(
                category=Category(name=category_name),
                confidence=0.9, # Arbitrary fallback confidence
                source="llm"
            )
        except Exception as e:
            logger.error(f"LLM Error: {e}")
            return None

    def learn(self, transaction: Transaction, category: Category):
        # We don't fine-tune the LLM in this simple version.
        # We could add to few-shot examples in future prompts.
        pass
