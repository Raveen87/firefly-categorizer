from pydantic import BaseModel

from firefly_categorizer.models import Category, Transaction


class CategorizeRequest(BaseModel):
    transaction: Transaction


class LearnRequest(BaseModel):
    transaction: Transaction
    category: Category
    transaction_id: str | None = None
    suggested_category: str | None = None
    existing_tags: list[str] | None = None
