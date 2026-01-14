from typing import Annotated

from fastapi import APIRouter, Depends

from firefly_categorizer.api.dependencies import (
    get_firefly_optional,
    get_pipeline,
    get_service,
)
from firefly_categorizer.api.schemas import CategorizeRequest
from firefly_categorizer.integration.firefly import FireflyClient
from firefly_categorizer.manager import CategorizerService
from firefly_categorizer.models import CategorizationResult
from firefly_categorizer.services.categorization import CategorizationPipeline
from firefly_categorizer.services.firefly_data import fetch_category_names

router = APIRouter()


@router.post("/categorize", response_model=CategorizationResult | None)
async def categorize_transaction(
    req: CategorizeRequest,
    service: Annotated[CategorizerService, Depends(get_service)],
    pipeline: Annotated[CategorizationPipeline, Depends(get_pipeline)],
    firefly: Annotated[FireflyClient | None, Depends(get_firefly_optional)],
) -> CategorizationResult | None:
    valid_cats = None
    if firefly:
        categories = await fetch_category_names(firefly)
        if categories:
            valid_cats = categories

    return await pipeline.predict(req.transaction, valid_categories=valid_cats)


@router.get("/categories")
async def get_categories(
    firefly: Annotated[FireflyClient | None, Depends(get_firefly_optional)],
) -> list[str]:
    if not firefly:
        return []
    return await fetch_category_names(firefly)
