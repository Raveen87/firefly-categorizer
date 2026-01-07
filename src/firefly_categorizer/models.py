from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional

class Transaction(BaseModel):
    description: str
    amount: float
    date: datetime
    account_name: Optional[str] = None
    currency: str = "EUR"

class Category(BaseModel):
    name: str
    id: Optional[str] = None # Firefly ID or internal ID

class CategorizationResult(BaseModel):
    category: Category
    confidence: float # 0.0 to 1.0
    source: str # "memory", "tfidf", "llm"
    model_version: Optional[str] = None
