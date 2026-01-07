import os
from typing import Optional
from openai import OpenAI
from firefly_categorizer.models import Transaction, CategorizationResult, Category
from .base import Classifier

class LLMClassifier(Classifier):
    def __init__(self, api_key: str = None, model: str = "gpt-3.5-turbo"):
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.model = model

    def classify(self, transaction: Transaction) -> Optional[CategorizationResult]:
        try:
            prompt = f"""
            Categorize this financial transaction into a standard personal finance category.
            Transaction: {transaction.description}
            Amount: {transaction.amount} {transaction.currency}
            Date: {transaction.date}
            
            Return ONLY the category name. If unsure, return 'Uncategorized'.
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
            
            # Simple heuristic for confidence (LLMs are usually confident)
            return CategorizationResult(
                category=Category(name=category_name),
                confidence=0.9, # Arbitrary fallback confidence
                source="llm"
            )
        except Exception as e:
            print(f"LLM Error: {e}")
            return None

    def learn(self, transaction: Transaction, category: Category):
        # We don't fine-tune the LLM in this simple version.
        # We could add to few-shot examples in future prompts.
        pass
