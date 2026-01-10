from datetime import datetime

from pydantic import BaseModel


class Transaction(BaseModel):
    description: str
    amount: float
    date: datetime
    account_name: str | None = None
    currency: str = "EUR"

class Category(BaseModel):
    name: str
    id: str | None = None # Firefly ID or internal ID

class CategorizationResult(BaseModel):
    category: Category
    confidence: float # 0.0 to 1.0
    source: str # "memory", "tfidf", "llm"
    model_version: str | None = None
