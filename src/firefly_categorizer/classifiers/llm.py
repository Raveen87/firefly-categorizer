import os

from openai import OpenAI

from firefly_categorizer.logger import get_logger
from firefly_categorizer.models import CategorizationResult, Category, Transaction

from .base import Classifier

logger = get_logger(__name__)

class LLMClassifier(Classifier):
    def __init__(self, api_key: str | None = None, model: str = "gpt-3.5-turbo", base_url: str | None = None):
        self.client = OpenAI(
            api_key=api_key or os.getenv("OPENAI_API_KEY"),
            base_url=base_url or os.getenv("OPENAI_BASE_URL") or None
        )
        self.model = model

    def classify(
        self, transaction: Transaction, valid_categories: list[str] | None = None
    ) -> CategorizationResult | None:
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

            response = self.client.responses.create(
                model=self.model,
                instructions="You are a helpful financial assistant.",
                input=prompt,
                temperature=0.0
            )

            category_name = self._extract_output_text(response)
            if category_name is None:
                return None
            category_name = category_name.strip()

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

    @staticmethod
    def _extract_output_text(response: object) -> str | None:
        output_text = getattr(response, "output_text", None)
        if output_text:
            return output_text

        output = getattr(response, "output", None)
        if not output:
            return None

        parts: list[str] = []
        for item in output:
            content = getattr(item, "content", None)
            if not content:
                continue
            for block in content:
                block_type = getattr(block, "type", None)
                if block_type in {"output_text", "text"}:
                    text = getattr(block, "text", None)
                    if text:
                        parts.append(text)

        if parts:
            return "".join(parts)
        return None

    def learn(self, transaction: Transaction, category: Category) -> None:
        # We don't fine-tune the LLM in this simple version.
        # We could add to few-shot examples in future prompts.
        pass
