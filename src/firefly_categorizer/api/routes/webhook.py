from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from firefly_categorizer.api.dependencies import get_firefly, get_pipeline, get_service
from firefly_categorizer.core import settings
from firefly_categorizer.domain.transactions import (
    extract_webhook_transaction_id,
    extract_webhook_transaction_snapshot,
    parse_webhook_transaction,
)
from firefly_categorizer.integration.firefly import FireflyClient
from firefly_categorizer.logger import get_logger
from firefly_categorizer.manager import CategorizerService
from firefly_categorizer.services.categorization import CategorizationPipeline
from firefly_categorizer.services.firefly_data import fetch_category_names

logger = get_logger(__name__)

router = APIRouter()


@router.post("/webhook/firefly")
async def firefly_webhook(
    request: Request,
    service: Annotated[CategorizerService, Depends(get_service)],
    firefly: Annotated[FireflyClient, Depends(get_firefly)],
    pipeline: Annotated[CategorizationPipeline, Depends(get_pipeline)],
) -> dict[str, str]:
    try:
        payload = await request.json()
    except Exception as exc:
        logger.warning("[WEBHOOK] Received invalid JSON payload.")
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    if not isinstance(payload, dict):
        logger.warning("[WEBHOOK] Unexpected payload type: %s.", type(payload).__name__)
        return {"status": "ignored", "reason": "unexpected payload"}

    event_name = payload.get("event") or payload.get("trigger") or payload.get("type")
    event_suffix = f" ({event_name})" if event_name else ""
    logger.info("[WEBHOOK] Firefly webhook received%s.", event_suffix)

    tx_id = extract_webhook_transaction_id(payload)
    snapshot = extract_webhook_transaction_snapshot(payload)
    if not snapshot and tx_id:
        snapshot = await firefly.get_transaction(tx_id)

    if not snapshot:
        logger.warning("[WEBHOOK] Missing transaction details; skipping.")
        return {"status": "ignored", "reason": "missing transaction details"}

    tx_id = tx_id or extract_webhook_transaction_id(snapshot) or "unknown"
    tx_obj, existing_category, existing_tags = parse_webhook_transaction(snapshot)

    if not tx_obj:
        logger.warning("[WEBHOOK] Missing transaction fields; skipping.")
        return {"status": "ignored", "reason": "missing transaction fields"}

    if existing_category:
        logger.info(
            "[WEBHOOK] Transaction %s already categorized as '%s'; skipping.",
            tx_id,
            existing_category,
        )
        return {"status": "ignored", "reason": "already categorized"}

    valid_categories = await fetch_category_names(firefly)
    if not valid_categories:
        valid_categories = None

    logger.debug("[WEBHOOK] Starting categorization for transaction ID: %s", tx_id)
    prediction = await pipeline.predict(
        tx_obj,
        valid_categories=valid_categories,
    )

    if not prediction:
        logger.info("[WEBHOOK] No prediction available for transaction %s; skipping.", tx_id)
        return {"status": "ignored", "reason": "no prediction"}

    auto_approve_threshold = settings.get_env_float("AUTO_APPROVE_THRESHOLD", 0.0)
    reason, threshold_value = pipeline.auto_approval_reason(
        tx_id,
        prediction,
        threshold=auto_approve_threshold,
        log_disabled=True,
        log_low_confidence=True,
    )
    if reason == "disabled":
        return {"status": "ignored", "reason": "auto-approve disabled"}
    if reason == "low_confidence":
        return {"status": "ignored", "reason": "low confidence"}

    if tx_id == "unknown":
        logger.warning("[WEBHOOK] Missing transaction ID; cannot update Firefly.")
        return {"status": "ignored", "reason": "missing transaction id"}

    success = await pipeline.apply_auto_approval(
        tx_id,
        tx_obj,
        prediction,
        existing_tags,
        include_existing_when_no_auto=True,
        log_auto_approve=False,
        threshold=threshold_value,
    )

    if success:
        logger.info(
            "[WEBHOOK] Auto-categorized transaction %s as '%s' (confidence %.2f).",
            tx_id,
            prediction.category.name,
            prediction.confidence,
        )
        return {"status": "updated"}

    logger.warning(
        "[WEBHOOK] Failed to update transaction %s with category '%s'.",
        tx_id,
        prediction.category.name,
    )
    return {"status": "failed"}
