import asyncio
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from firefly_categorizer.api.dependencies import (
    get_firefly_optional,
    get_pipeline_optional,
    get_service_optional,
)
from firefly_categorizer.core import settings
from firefly_categorizer.domain.transactions import (
    build_transaction_payload,
    build_transaction_snapshot,
    build_transactions_display,
)
from firefly_categorizer.integration.firefly import FireflyClient
from firefly_categorizer.manager import CategorizerService
from firefly_categorizer.services.categorization import CategorizationPipeline
from firefly_categorizer.services.firefly_data import fetch_category_names, resolve_date_range

router = APIRouter()


@router.get("/api/categorize-stream")
async def categorize_stream(
    service: Annotated[CategorizerService | None, Depends(get_service_optional)],
    firefly: Annotated[FireflyClient | None, Depends(get_firefly_optional)],
    pipeline: Annotated[CategorizationPipeline | None, Depends(get_pipeline_optional)],
    start_date: str | None = None,
    end_date: str | None = None,
    scope: str | None = None,
    page: int = 1,
    limit: int = 50,
) -> StreamingResponse:
    async def generate() -> Any:
        if not service or not firefly or not pipeline:
            yield "data: {\"error\": \"Service not initialized\"}\n\n"
            return

        start_date_obj, end_date_obj = resolve_date_range(start_date, end_date, scope)

        result = await firefly.get_transactions(
            start_date=start_date_obj,
            end_date=end_date_obj,
            page=page,
            limit=limit,
        )

        raw_txs = result.get("data", [])

        category_list = await fetch_category_names(firefly, sort=True)
        auto_approve_threshold = settings.get_env_float("AUTO_APPROVE_THRESHOLD", 0.0)

        for idx, t_data in enumerate(raw_txs):
            if idx % settings.STREAM_YIELD_EVERY == 0:
                await asyncio.sleep(0)

            snapshot = build_transaction_snapshot(t_data)
            prediction, existing_cat, auto_approved = await pipeline.predict_for_snapshot(
                snapshot,
                valid_categories=category_list if category_list else None,
                auto_approve_threshold=auto_approve_threshold,
            )

            payload = {
                "id": snapshot.transaction_id,
                "prediction": prediction.model_dump() if prediction else None,
                "existing_category": existing_cat,
                "auto_approved": auto_approved,
            }

            yield f"data: {json.dumps(payload)}\n\n"

        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream", headers=settings.SSE_HEADERS)


@router.get("/api/transactions")
async def get_transactions(
    service: Annotated[CategorizerService | None, Depends(get_service_optional)],
    firefly: Annotated[FireflyClient | None, Depends(get_firefly_optional)],
    pipeline: Annotated[CategorizationPipeline | None, Depends(get_pipeline_optional)],
    start_date: str | None = None,
    end_date: str | None = None,
    scope: str | None = None,
    predict: bool = False,
    page: int = 1,
    limit: int = 50,
) -> dict[str, Any]:
    transactions_display: list[dict[str, Any]] = []
    category_list: list[str] = []
    pagination: dict[str, Any] = {}

    if firefly:
        category_list = await fetch_category_names(firefly, sort=True)

        start_date_obj, end_date_obj = resolve_date_range(start_date, end_date, scope)

        result = await firefly.get_transactions(
            start_date=start_date_obj,
            end_date=end_date_obj,
            page=page,
            limit=limit,
        )

        raw_txs = result.get("data", [])
        pagination = result.get("meta", {})

        if not predict:
            transactions_display = await asyncio.to_thread(build_transactions_display, raw_txs)
        else:
            auto_approve_threshold = settings.get_env_float("AUTO_APPROVE_THRESHOLD", 0.0)
            for idx, t_data in enumerate(raw_txs):
                if idx % settings.STREAM_YIELD_EVERY == 0:
                    await asyncio.sleep(0)

                snapshot = build_transaction_snapshot(t_data)
                prediction = None
                auto_approved = False

                existing_cat = snapshot.category_name
                if predict and service and pipeline:
                    prediction, existing_cat, auto_approved = await pipeline.predict_for_snapshot(
                        snapshot,
                        valid_categories=category_list if category_list else None,
                        auto_approve_threshold=auto_approve_threshold,
                    )

                transactions_display.append(build_transaction_payload(
                    snapshot,
                    prediction=prediction,
                    existing_category=existing_cat,
                    auto_approved=auto_approved,
                ))

    return {
        "transactions": transactions_display,
        "pagination": pagination,
    }
