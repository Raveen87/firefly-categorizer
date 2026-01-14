from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from firefly_categorizer.api.dependencies import (
    get_firefly_optional,
    get_service,
    get_training_manager,
)
from firefly_categorizer.api.schemas import LearnRequest
from firefly_categorizer.core import settings
from firefly_categorizer.domain.tags import merge_tags
from firefly_categorizer.integration.firefly import FireflyClient
from firefly_categorizer.logger import get_logger
from firefly_categorizer.manager import CategorizerService
from firefly_categorizer.services.training import TrainingManager

logger = get_logger(__name__)

router = APIRouter()


@router.post("/train")
async def train_models(
    training_manager: Annotated[TrainingManager, Depends(get_training_manager)],
) -> dict:
    return await training_manager.train_bulk()


@router.get("/train-stream")
async def train_stream(
    training_manager: Annotated[TrainingManager, Depends(get_training_manager)],
) -> StreamingResponse:
    return StreamingResponse(training_manager.stream(), media_type="text/event-stream")


@router.post("/train-pause")
async def pause_training(
    training_manager: Annotated[TrainingManager, Depends(get_training_manager)],
) -> dict[str, str]:
    if training_manager.request_pause():
        logger.info("[TRAIN] Pause requested by user.")
        return {"status": "pausing"}
    return {"status": "idle"}


@router.get("/train-status")
async def get_training_status(
    training_manager: Annotated[TrainingManager, Depends(get_training_manager)],
) -> dict:
    return training_manager.get_status()


@router.post("/train-reset")
async def reset_training_state(
    training_manager: Annotated[TrainingManager, Depends(get_training_manager)],
) -> dict[str, int | str]:
    if training_manager.active:
        raise HTTPException(status_code=409, detail="Training in progress")
    cleared = training_manager.clear_seen_ids()
    return {"status": "cleared", "cleared": cleared}


@router.post("/clear-models")
async def clear_models(
    service: Annotated[CategorizerService, Depends(get_service)],
    training_manager: Annotated[TrainingManager, Depends(get_training_manager)],
) -> dict[str, str]:
    service.clear_models()
    training_manager.reset_state()
    return {"status": "success", "message": "All models cleared"}


@router.post("/learn")
async def learn_transaction(
    req: LearnRequest,
    service: Annotated[CategorizerService, Depends(get_service)],
    firefly: Annotated[FireflyClient | None, Depends(get_firefly_optional)],
) -> dict[str, str]:
    is_model_suggested = req.suggested_category and req.suggested_category == req.category.name
    source = "model" if is_model_suggested else "manual"

    logger.info(
        "[CATEGORIZE] Transaction ID: %s -> Category: '%s' (Source: %s)",
        req.transaction_id or "N/A",
        req.category.name,
        source,
    )

    service.learn(req.transaction, req.category)

    firefly_update_status = "skipped"
    if firefly and req.transaction_id:
        manual_tags = settings.get_env_tags("MANUAL_TAGS")
        tags_payload = merge_tags(req.existing_tags, manual_tags) if manual_tags else None
        success = await firefly.update_transaction(
            req.transaction_id,
            req.category.name,
            tags=tags_payload,
        )
        firefly_update_status = "success" if success else "failed"

    return {
        "status": "success",
        "message": "Learned new transaction",
        "firefly_update": firefly_update_status,
        "source": source,
    }
