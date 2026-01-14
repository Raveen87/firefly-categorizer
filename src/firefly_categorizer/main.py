import asyncio
import json
import os
from collections import deque
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from time import perf_counter
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from firefly_categorizer.integration.firefly import FireflyClient
from firefly_categorizer.logger import get_logger, get_logging_config, setup_logging
from firefly_categorizer.manager import CategorizerService
from firefly_categorizer.models import CategorizationResult, Category, Transaction

def _load_environment() -> None:
    config_dir = os.getenv("CONFIG_DIR")
    if config_dir:
        dotenv_path = os.path.join(config_dir, ".env")
        loaded = load_dotenv(dotenv_path=dotenv_path)
        if not loaded:
            load_dotenv()
    else:
        load_dotenv()

def _ensure_dir(path: str | None) -> None:
    if path and path not in {".", "./"}:
        os.makedirs(path, exist_ok=True)

# Load environment variables
_load_environment()

DATA_DIR = os.getenv("DATA_DIR", ".")
LOG_DIR = os.getenv("LOG_DIR")
CONFIG_DIR = os.getenv("CONFIG_DIR")

_ensure_dir(DATA_DIR)
_ensure_dir(LOG_DIR)
_ensure_dir(CONFIG_DIR)

# Setup logging
setup_logging()
logger = get_logger(__name__)

# SSE headers to reduce proxy buffering and keep connections alive.
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
STREAM_YIELD_EVERY = 50
DEFAULT_TRAINING_PAGE_SIZE = 50

# Global service instance
service: CategorizerService | None = None
firefly: FireflyClient | None = None
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "web/templates"))
training_pause_event = asyncio.Event()
training_active = False
training_seen_ids: set[str] = set()
training_status: dict[str, Any] = {"stage": "idle", "active": False}

def _is_all_scope(scope: str | None) -> bool:
    return (scope or "").lower() == "all"

_SENSITIVE_ENV_KEYS = (
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PASS",
    "AUTH",
    "BEARER",
    "PRIVATE",
)

_ENV_KEYS_TO_LOG = (
    "LOG_LEVEL",
    "FIREFLY_URL",
    "FIREFLY_TOKEN",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "OPENAI_BASE_URL",
    "AUTO_APPROVE_THRESHOLD",
    "TRAINING_PAGE_SIZE",
    "MANUAL_TAGS",
    "AUTO_APPROVE_TAGS",
)

def _should_mask_env_value(name: str, value: str) -> bool:
    upper_name = name.upper()
    if any(marker in upper_name for marker in _SENSITIVE_ENV_KEYS):
        return True
    if value.startswith("sk-") or value.startswith("rk-"):
        return True
    if value.startswith("Bearer ") or value.startswith("bearer "):
        return True
    if value.startswith("eyJ") and value.count(".") == 2:
        return True
    return False

def _mask_env_value(name: str, value: str) -> str:
    sanitized = value.replace("\r", "\\r").replace("\n", "\\n")
    if not _should_mask_env_value(name, sanitized):
        return sanitized
    if len(sanitized) <= 4:
        return "****"
    return f"{sanitized[:2]}...{sanitized[-2:]}"

def _log_environment() -> None:
    logger.info("[ENV] Logging configured environment variables (masked where needed).")
    for key in _ENV_KEYS_TO_LOG:
        raw_value = os.getenv(key)
        value = "<unset>" if raw_value is None else _mask_env_value(key, raw_value)
        logger.info(f"[ENV] {key}={value}")

def _parse_tag_list(raw_tags: str | None) -> list[str]:
    if not raw_tags:
        return []
    parts = [part.strip() for part in raw_tags.split(",")]
    tags = []
    seen = set()
    for part in parts:
        if part and part not in seen:
            tags.append(part)
            seen.add(part)
    return tags

def _normalize_tags(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        tags = []
        seen = set()
        for item in value:
            tag = str(item).strip()
            if tag and tag not in seen:
                tags.append(tag)
                seen.add(tag)
        return tags
    if isinstance(value, str):
        return _parse_tag_list(value)
    return []

def _merge_tags(existing_tags: list[str] | None, new_tags: list[str]) -> list[str]:
    merged = []
    seen = set()
    for tag in existing_tags or []:
        if tag and tag not in seen:
            merged.append(tag)
            seen.add(tag)
    for tag in new_tags:
        if tag and tag not in seen:
            merged.append(tag)
            seen.add(tag)
    return merged

def _get_env_tags(name: str) -> list[str]:
    return _parse_tag_list(os.getenv(name))

def _get_env_int(name: str, default: int, min_value: int | None = None) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning(f"[ENV] Invalid {name}='{raw}', using default {default}.")
        return default
    if min_value is not None and value < min_value:
        logger.warning(f"[ENV] {name}='{raw}' below minimum {min_value}, using default {default}.")
        return default
    return value

TRAINING_PAGE_SIZE = _get_env_int(
    "TRAINING_PAGE_SIZE",
    DEFAULT_TRAINING_PAGE_SIZE,
    min_value=1
)

def _format_duration(seconds: float) -> str:
    if seconds <= 0:
        return "0 ms"
    if seconds < 1:
        return f"{seconds * 1000:.1f} ms"
    if seconds < 60:
        return f"{seconds:.2f} s"
    return f"{seconds / 60:.2f} min"

_WEBHOOK_ID_KEYS = ("transaction_id", "resource_id", "object_id", "entity_id", "id")

def _iter_webhook_containers(payload: Any) -> list[dict[str, Any]]:
    containers: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        containers.append(payload)
        for key in ("data", "content", "transaction", "attributes"):
            value = payload.get(key)
            if isinstance(value, dict):
                containers.append(value)

    for container in list(containers):
        attrs = container.get("attributes")
        if isinstance(attrs, dict):
            containers.append(attrs)
        for key in ("data", "content"):
            nested = container.get(key)
            if isinstance(nested, dict):
                containers.append(nested)
        txs = container.get("transactions")
        if isinstance(txs, list) and txs:
            first_tx = txs[0]
            if isinstance(first_tx, dict):
                containers.append(first_tx)

    return containers

def _extract_webhook_transaction_id(payload: dict[str, Any]) -> str | None:
    for container in _iter_webhook_containers(payload):
        for key in _WEBHOOK_ID_KEYS:
            value = container.get(key)
            if value is not None and str(value).strip():
                return str(value)
    return None

def _extract_webhook_transaction_snapshot(payload: dict[str, Any]) -> dict[str, Any] | None:
    for container in _iter_webhook_containers(payload):
        if "attributes" in container or "transactions" in container:
            return container
        if any(key in container for key in ("description", "amount", "date", "currency_code")):
            return container
    return None

def _parse_webhook_transaction(snapshot: dict[str, Any]) -> tuple[Transaction | None, str | None, list[str]]:
    attrs = snapshot.get("attributes") if isinstance(snapshot.get("attributes"), dict) else snapshot
    tx_details = attrs
    if isinstance(attrs.get("transactions"), list) and attrs["transactions"]:
        tx_details = attrs["transactions"][0]
    if not isinstance(tx_details, dict):
        return None, None, []

    description = str(tx_details.get("description") or "")
    try:
        amount = float(tx_details.get("amount", 0.0))
    except (TypeError, ValueError):
        amount = 0.0
    currency = tx_details.get("currency_code") or tx_details.get("currency") or "EUR"
    date_raw = tx_details.get("date") or tx_details.get("created_at") or tx_details.get("updated_at")

    if isinstance(date_raw, datetime):
        date_value = date_raw
    elif isinstance(date_raw, str):
        try:
            date_value = datetime.fromisoformat(date_raw.replace("Z", "+00:00"))
        except ValueError:
            date_value = datetime.now()
    else:
        date_value = datetime.now()

    category_name = tx_details.get("category_name") or attrs.get("category_name")
    tags = _normalize_tags(tx_details.get("tags") or attrs.get("tags"))

    if not description:
        return None, category_name, tags

    return Transaction(
        description=description,
        amount=amount,
        date=date_value,
        currency=currency
    ), category_name, tags

def _process_training_page(
    svc: CategorizerService,
    page_txs: list[dict[str, Any]],
    seen_ids: set[str]
) -> tuple[int, int, int, list[float]]:
    trained_count = 0
    skipped_uncategorized = 0
    skipped_duplicate = 0
    durations: list[float] = []

    for t_data in page_txs:
        tx_id_raw = t_data.get("id")
        tx_id = str(tx_id_raw) if tx_id_raw is not None else None
        if tx_id and tx_id in seen_ids:
            skipped_duplicate += 1
            continue

        attrs = t_data.get("attributes", {}).get("transactions", [{}])[0]
        desc = attrs.get("description", "")
        amount = float(attrs.get("amount", 0.0))
        curr = attrs.get("currency_code", "EUR")
        date_str = attrs.get("date", "")
        category_name = attrs.get("category_name")

        # Skip uncategorized transactions
        if not category_name:
            skipped_uncategorized += 1
            continue

        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError:
            dt = datetime.now()

        tx_obj = Transaction(
            description=desc,
            amount=amount,
            date=dt,
            currency=curr
        )

        start = perf_counter()
        svc.learn(tx_obj, Category(name=category_name))
        durations.append(perf_counter() - start)
        trained_count += 1
        if tx_id:
            seen_ids.add(tx_id)

    return trained_count, skipped_uncategorized, skipped_duplicate, durations

def _build_transactions_display(raw_txs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    transactions_display = []
    for t_data in raw_txs:
        attrs = t_data.get("attributes", {}).get("transactions", [{}])[0]
        desc = attrs.get("description", "")
        amount = float(attrs.get("amount", 0.0))
        curr = attrs.get("currency_code", "EUR")
        date_str = attrs.get("date", "")
        existing_cat = attrs.get("category_name")
        existing_tags = _normalize_tags(attrs.get("tags") or t_data.get("attributes", {}).get("tags"))
        tx_id = t_data.get("id")
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError:
            dt = datetime.now()

        tx_obj = Transaction(
            description=desc,
            amount=amount,
            date=dt,
            currency=curr
        )

        transactions_display.append({
            "id": tx_id,
            "date_formatted": dt.strftime("%Y-%m-%d"),
            "description": desc,
            "amount": amount,
            "currency": curr,
            "prediction": None,
            "existing_category": existing_cat,
            "existing_tags": existing_tags,
            "auto_approved": False,
            "raw_obj": tx_obj.model_dump_json() # For JS to pick up
        })

    return transactions_display

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global service, firefly
    # Initialize service on startup
    logger.info("Initializing services...")
    _log_environment()

    # Check Environment Variables
    if not os.getenv("FIREFLY_URL") or not os.getenv("FIREFLY_TOKEN"):
        logger.warning("FIREFLY_URL or FIREFLY_TOKEN not set. Firefly integration will be disabled.")

    if not os.getenv("OPENAI_API_KEY"):
        logger.info("OPENAI_API_KEY not set. OpenAI integration will be disabled.")

    service = CategorizerService(data_dir=DATA_DIR)
    firefly = FireflyClient() # Will use env vars
    logger.info("Services initialized.")
    yield
    logger.info("Service shutting down.")

app = FastAPI(title="Firefly Categorizer", lifespan=lifespan)

# Mount static files
static_dir = os.path.join(os.path.dirname(__file__), "web/static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

class CategorizeRequest(BaseModel):
    transaction: Transaction

class LearnRequest(BaseModel):
    transaction: Transaction
    category: Category
    transaction_id: str | None = None
    suggested_category: str | None = None  # What the model suggested
    existing_tags: list[str] | None = None

@app.post("/categorize", response_model=CategorizationResult | None)
async def categorize_transaction(req: CategorizeRequest) -> CategorizationResult | None:
    if not service:
        raise HTTPException(status_code=500, detail="Service not initialized")

    valid_cats = None
    if firefly:
        # Fetch valid categories to constrain prediction
        raw_cats = await firefly.get_categories()
        if raw_cats:
            valid_cats = [c["attributes"]["name"] for c in raw_cats]

    return service.categorize(req.transaction, valid_categories=valid_cats)

@app.get("/categories")
async def get_categories() -> list[str]:
    if not firefly:
        return []
    raw = await firefly.get_categories()
    return [c["attributes"]["name"] for c in raw]

@app.post("/train")
async def train_models() -> dict[str, Any]:
    """
    Train models using all existing categorized transactions from Firefly.
    """
    if not service:
        raise HTTPException(status_code=500, detail="Service not initialized")
    if not firefly:
        raise HTTPException(status_code=500, detail="Firefly not configured")

    logger.info("[TRAIN] Starting bulk training from Firefly data...")

    trained_count = 0
    skipped_count = 0
    skipped_duplicate = 0
    total_fetched = 0
    seen_ids = training_seen_ids

    async for page_txs, _ in firefly.yield_transactions(limit_per_page=TRAINING_PAGE_SIZE):
        total_fetched += len(page_txs)

        page_trained, page_skipped_uncategorized, page_skipped_duplicate, _ = await asyncio.to_thread(
            _process_training_page, service, page_txs, seen_ids
        )
        trained_count += page_trained
        skipped_count += page_skipped_uncategorized
        skipped_duplicate += page_skipped_duplicate

        logger.info(
            "[TRAIN] Page processed. Skipped (already trained): %s, "
            "Skipped (uncategorized): %s, Total trained so far: %s",
            page_skipped_duplicate,
            page_skipped_uncategorized,
            trained_count
        )

    logger.info(
        f"[TRAIN] Complete! Trained: {trained_count}, "
        f"Skipped (no category): {skipped_count}, "
        f"Skipped (already trained): {skipped_duplicate}"
    )

    return {
        "status": "success",
        "trained": trained_count,
        "skipped": skipped_count,
        "total": total_fetched,
        "fetched": total_fetched
    }

@app.get("/train-stream")
async def train_stream() -> StreamingResponse:
    """
    SSE endpoint for training with real-time progress updates.
    """
    async def generate() -> AsyncGenerator[str, None]:
        global training_active
        if not service or not firefly:
            training_status.clear()
            training_status.update({
                "stage": "error",
                "message": "Service not initialized",
                "active": False
            })
            yield f"data: {json.dumps({'stage': 'error', 'message': 'Service not initialized'})}\n\n"
            return

        trained_count = 0
        skipped_count = 0
        skipped_duplicate = 0
        total_fetched = 0
        total_estimate = 0
        last_durations: deque[float] = deque(maxlen=10)
        avg_last_10_seconds = 0.0
        pause_requested = False
        seen_ids = training_seen_ids

        # Notify start
        training_active = True
        training_pause_event.clear()
        training_status.clear()
        training_status.update({
            "stage": "start",
            "active": True,
            "trained": 0,
            "skipped": 0,
            "fetched": 0,
            "total": 0,
            "percent": 0,
            "avg_last_10_seconds": 0.0,
            "avg_last_10_display": None
        })
        yield f"data: {json.dumps({'stage': 'start'})}\n\n"

        try:
            async for page_txs, meta in firefly.yield_transactions(limit_per_page=TRAINING_PAGE_SIZE):
                if training_pause_event.is_set():
                    pause_requested = True
                    break
                # Update total estimate from metadata
                if total_estimate == 0:
                    total_estimate = meta.get("total", 0)

                total_fetched += len(page_txs)

                page_trained, page_skipped_uncategorized, page_skipped_duplicate, page_durations = await asyncio.to_thread(
                    _process_training_page, service, page_txs, seen_ids
                )
                trained_count += page_trained
                skipped_count += page_skipped_uncategorized
                skipped_duplicate += page_skipped_duplicate
                last_durations.extend(page_durations)
                avg_last_10_seconds = (
                    sum(last_durations) / len(last_durations)
                    if last_durations
                    else 0.0
                )

                logger.info(
                    "[TRAIN] Page processed. Skipped (already trained): %s, "
                    "Skipped (uncategorized): %s, Total trained so far: %s",
                    page_skipped_duplicate,
                    page_skipped_uncategorized,
                    trained_count
                )

                if training_pause_event.is_set():
                    pause_requested = True
                    break

                # Yield progress after each page
                percent = round(total_fetched / total_estimate * 100, 1) if total_estimate > 0 else 0
                status_payload = {
                    'stage': 'processing',
                    'trained': trained_count,
                    'skipped': skipped_count,
                    'fetched': total_fetched,
                    'total': total_estimate,
                    'percent': percent,
                    'avg_last_10_seconds': avg_last_10_seconds,
                    'avg_last_10_display': _format_duration(avg_last_10_seconds) if last_durations else None
                }
                training_status.clear()
                training_status.update({**status_payload, "active": True})
                yield f"data: {json.dumps(status_payload)}\n\n"

            if pause_requested:
                percent = round(total_fetched / total_estimate * 100, 1) if total_estimate > 0 else 0
                logger.info(
                    "[TRAIN] Training paused. Trained: %s, Skipped (no category): %s, "
                    "Skipped (already trained): %s",
                    trained_count,
                    skipped_count,
                    skipped_duplicate
                )
                pause_payload = {
                    'stage': 'paused',
                    'trained': trained_count,
                    'skipped': skipped_count,
                    'total_fetched': total_fetched,
                    'fetched': total_fetched,
                    'total': total_estimate,
                    'percent': percent,
                    'avg_last_10_seconds': avg_last_10_seconds if last_durations else 0.0,
                    'avg_last_10_display': _format_duration(avg_last_10_seconds) if last_durations else None
                }
                training_status.clear()
                training_status.update({**pause_payload, "active": False})
                yield f"data: {json.dumps(pause_payload)}\n\n"
                return

            # Stage Complete
            complete_payload = {
                'stage': 'complete',
                'trained': trained_count,
                'skipped': skipped_count,
                'total_fetched': total_fetched,
                'avg_last_10_seconds': avg_last_10_seconds if last_durations else 0.0,
                'avg_last_10_display': _format_duration(avg_last_10_seconds) if last_durations else None
            }
            training_status.clear()
            training_status.update({**complete_payload, "active": False})
            yield f"data: {json.dumps(complete_payload)}\n\n"
        finally:
            training_active = False
            training_pause_event.clear()
            training_status["active"] = False

    return StreamingResponse(generate(), media_type="text/event-stream")

@app.post("/train-pause")
async def pause_training() -> dict[str, str]:
    if training_active:
        logger.info("[TRAIN] Pause requested by user.")
        training_pause_event.set()
        return {"status": "pausing"}
    return {"status": "idle"}

@app.get("/train-status")
async def get_training_status() -> dict[str, Any]:
    status = dict(training_status)
    status["active"] = training_active
    return status

@app.post("/train-reset")
async def reset_training_state() -> dict[str, Any]:
    if training_active:
        raise HTTPException(status_code=409, detail="Training in progress")
    cleared = len(training_seen_ids)
    training_seen_ids.clear()
    return {"status": "cleared", "cleared": cleared}

@app.post("/clear-models")
async def clear_models() -> dict[str, str]:
    if not service:
        raise HTTPException(status_code=500, detail="Service not initialized")

    service.clear_models()
    training_seen_ids.clear()
    training_status.clear()
    training_status.update({"stage": "idle", "active": False})
    return {"status": "success", "message": "All models cleared"}

@app.post("/learn")
async def learn_transaction(req: LearnRequest) -> dict[str, Any]:
    if not service:
        raise HTTPException(status_code=500, detail="Service not initialized")

    # Determine if this was model-suggested or manual
    is_model_suggested = req.suggested_category and req.suggested_category == req.category.name
    source = "model" if is_model_suggested else "manual"

    # Log the categorization
    logger.info(
        f"[CATEGORIZE] Transaction ID: {req.transaction_id or 'N/A'} -> "
        f"Category: '{req.category.name}' (Source: {source})"
    )

    # 1. Update Local Models
    service.learn(req.transaction, req.category)

    # 2. Update Firefly III (if ID provided)
    firefly_update_status = "skipped"
    if firefly and req.transaction_id:
        manual_tags = _get_env_tags("MANUAL_TAGS")
        tags_payload = _merge_tags(req.existing_tags, manual_tags) if manual_tags else None
        success = await firefly.update_transaction(
            req.transaction_id,
            req.category.name,
            tags=tags_payload
        )
        firefly_update_status = "success" if success else "failed"

    return {
        "status": "success",
        "message": "Learned new transaction",
        "firefly_update": firefly_update_status,
        "source": source
    }

@app.get("/api/categorize-stream")
async def categorize_stream(
    start_date: str | None = None,
    end_date: str | None = None,
    scope: str | None = None,
    page: int = 1,
    limit: int = 50
) -> StreamingResponse:
    async def generate() -> AsyncGenerator[str, None]:
        if not service or not firefly:
            yield f"data: {json.dumps({'error': 'Service not initialized'})}\n\n"
            return

        # Use same logic as get_transactions to fetch raw data
        use_all_scope = _is_all_scope(scope)
        if use_all_scope:
            start_date_obj = None
            end_date_obj = None
        else:
            # Default dates: last 30 days
            if not start_date:
                s_date = datetime.now() - timedelta(days=30)
                start_date_obj = s_date
            else:
                start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")

            if not end_date:
                e_date = datetime.now()
                end_date_obj = e_date
            else:
                end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")

        result = await firefly.get_transactions(
            start_date=start_date_obj,
            end_date=end_date_obj,
            page=page,
            limit=limit
        )

        raw_txs = result.get("data", [])

        # Get categories for prediction context
        raw_cats = await firefly.get_categories()
        category_list = sorted([c["attributes"]["name"] for c in raw_cats])

        auto_approve_threshold = float(os.getenv("AUTO_APPROVE_THRESHOLD", "0"))

        for idx, t_data in enumerate(raw_txs):
            if idx % STREAM_YIELD_EVERY == 0:
                await asyncio.sleep(0)

            attrs = t_data.get("attributes", {}).get("transactions", [{}])[0]
            desc = attrs.get("description", "")
            amount = float(attrs.get("amount", 0.0))
            curr = attrs.get("currency_code", "EUR")
            date_str = attrs.get("date", "")
            existing_cat = attrs.get("category_name")
            existing_tags = _normalize_tags(attrs.get("tags") or t_data.get("attributes", {}).get("tags"))
            tx_id = t_data.get("id")

            try:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except ValueError:
                dt = datetime.now()

            tx_obj = Transaction(
                description=desc,
                amount=amount,
                date=dt,
                currency=curr
            )

            prediction = None
            auto_approved = False

            if not existing_cat and service:
                prediction = await asyncio.to_thread(
                    service.categorize,
                    tx_obj,
                    valid_categories=category_list if category_list else None
                )

                if prediction and auto_approve_threshold > 0 and prediction.confidence >= auto_approve_threshold:
                    logger.info(
                        f"[AUTO-APPROVE] Transaction {tx_id}: '{prediction.category.name}' "
                        f"(confidence: {prediction.confidence:.2f} >= {auto_approve_threshold})"
                    )
                    auto_tags = _get_env_tags("AUTO_APPROVE_TAGS")
                    tags_payload = _merge_tags(existing_tags, auto_tags) if auto_tags else None
                    success = await firefly.update_transaction(
                        tx_id,
                        prediction.category.name,
                        tags=tags_payload
                    )
                    if success:
                        await asyncio.to_thread(service.learn, tx_obj, prediction.category)
                        existing_cat = prediction.category.name
                        auto_approved = True
                        prediction = None

            payload = {
                "id": tx_id,
                "prediction": prediction.model_dump() if prediction else None,
                "existing_category": existing_cat,
                "auto_approved": auto_approved
            }

            yield f"data: {json.dumps(payload)}\n\n"

        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream", headers=SSE_HEADERS)

@app.get("/api/transactions")
async def get_transactions(
    start_date: str | None = None,
    end_date: str | None = None,
    scope: str | None = None,
    predict: bool = False,
    page: int = 1,
    limit: int = 50
) -> dict[str, Any]:
    transactions_display = []
    category_list = []
    pagination = {}

    if firefly:
        # Fetch categories to validate predictions
        raw_cats = await firefly.get_categories()
        category_list = sorted([c["attributes"]["name"] for c in raw_cats])

        use_all_scope = _is_all_scope(scope)
        if use_all_scope:
            start_date_obj = None
            end_date_obj = None
        else:
            # Default dates: last 30 days
            if not start_date:
                s_date = datetime.now() - timedelta(days=30)
                start_date_obj = s_date
            else:
                start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")

            if not end_date:
                e_date = datetime.now()
                end_date_obj = e_date
            else:
                end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")

        result = await firefly.get_transactions(
            start_date=start_date_obj,
            end_date=end_date_obj,
            page=page,
            limit=limit
        )

        raw_txs = result.get("data", [])
        pagination = result.get("meta", {})

        if not predict:
            transactions_display = await asyncio.to_thread(_build_transactions_display, raw_txs)
        else:
            # Get auto-approve threshold from env (0 = disabled)
            auto_approve_threshold = float(os.getenv("AUTO_APPROVE_THRESHOLD", "0"))

            for idx, t_data in enumerate(raw_txs):
                if idx % STREAM_YIELD_EVERY == 0:
                    await asyncio.sleep(0)

                attrs = t_data.get("attributes", {}).get("transactions", [{}])[0]
                desc = attrs.get("description", "")
                amount = float(attrs.get("amount", 0.0))
                curr = attrs.get("currency_code", "EUR")
                date_str = attrs.get("date", "")
                existing_cat = attrs.get("category_name") # May be None or string
                existing_tags = _normalize_tags(attrs.get("tags") or t_data.get("attributes", {}).get("tags"))
                tx_id = t_data.get("id")
                try:
                    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except ValueError:
                    dt = datetime.now() # Fallback

                tx_obj = Transaction(
                    description=desc,
                    amount=amount,
                    date=dt,
                    currency=curr
                )

                # Only predict if not already categorized
                prediction = None
                auto_approved = False
                if predict and not existing_cat and service:
                    prediction = await asyncio.to_thread(
                        service.categorize,
                        tx_obj,
                        valid_categories=category_list if category_list else None
                    )

                    # Auto-approve if confidence exceeds threshold
                    if prediction and auto_approve_threshold > 0 and prediction.confidence >= auto_approve_threshold:
                        logger.info(
                            f"[AUTO-APPROVE] Transaction {tx_id}: '{prediction.category.name}' "
                            f"(confidence: {prediction.confidence:.2f} >= {auto_approve_threshold})"
                        )
                        # Update Firefly
                        auto_tags = _get_env_tags("AUTO_APPROVE_TAGS")
                        tags_payload = _merge_tags(existing_tags, auto_tags) if auto_tags else None
                        success = await firefly.update_transaction(
                            tx_id,
                            prediction.category.name,
                            tags=tags_payload
                        )
                        if success:
                            # Learn from this auto-approval
                            await asyncio.to_thread(service.learn, tx_obj, prediction.category)
                            existing_cat = prediction.category.name  # Mark as categorized
                            auto_approved = True
                            prediction = None  # Clear prediction since it's now saved

                transactions_display.append({
                    "id": tx_id,
                    "date_formatted": dt.strftime("%Y-%m-%d"),
                    "description": desc,
                    "amount": amount,
                    "currency": curr,
                    "prediction": prediction,
                    "existing_category": existing_cat,
                    "existing_tags": existing_tags,
                    "auto_approved": auto_approved,
                    "raw_obj": tx_obj.model_dump_json() # For JS to pick up
                })

    return {
        "transactions": transactions_display,
        "pagination": pagination
    }

@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    start_date: str | None = None,
    end_date: str | None = None,
    scope: str | None = None
) -> HTMLResponse:
    category_list = []
    if firefly:
        raw_cats = await firefly.get_categories()
        category_list = sorted([c["attributes"]["name"] for c in raw_cats])

    # Just setup defaults for inputs, data fetched via JS
    if not start_date:
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")

    scope_mode = "all" if _is_all_scope(scope) else "range"

    return templates.TemplateResponse("index.html", {
        "request": request,
        "categories": category_list,
        "start_date": start_date,
        "end_date": end_date,
        "scope": scope_mode
    })

@app.get("/help", response_class=HTMLResponse)
async def help_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("help.html", {
        "request": request
    })

@app.get("/train", response_class=HTMLResponse)
async def train_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("train.html", {
        "request": request
    })

# Firefly Webhook Endpoint
@app.post("/webhook/firefly")
async def firefly_webhook(request: Request) -> dict[str, str]:
    """
    Handle Firefly III Webhook.
    """
    if not service:
        raise HTTPException(status_code=500, detail="Service not initialized")
    if not firefly:
        raise HTTPException(status_code=500, detail="Firefly not configured")

    try:
        payload = await request.json()
    except Exception:
        logger.warning("[WEBHOOK] Received invalid JSON payload.")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    if not isinstance(payload, dict):
        logger.warning("[WEBHOOK] Unexpected payload type: %s.", type(payload).__name__)
        return {"status": "ignored", "reason": "unexpected payload"}

    event_name = payload.get("event") or payload.get("trigger") or payload.get("type")
    event_suffix = f" ({event_name})" if event_name else ""
    logger.info(f"[WEBHOOK] Firefly webhook received{event_suffix}.")

    tx_id = _extract_webhook_transaction_id(payload)
    snapshot = _extract_webhook_transaction_snapshot(payload)
    if not snapshot and tx_id:
        snapshot = await firefly.get_transaction(tx_id)

    if not snapshot:
        logger.warning("[WEBHOOK] Missing transaction details; skipping.")
        return {"status": "ignored", "reason": "missing transaction details"}

    tx_id = tx_id or _extract_webhook_transaction_id(snapshot) or "unknown"
    tx_obj, existing_category, existing_tags = _parse_webhook_transaction(snapshot)

    if not tx_obj:
        logger.warning("[WEBHOOK] Missing transaction fields; skipping.")
        return {"status": "ignored", "reason": "missing transaction fields"}

    if existing_category:
        logger.info(
            "[WEBHOOK] Transaction %s already categorized as '%s'; skipping.",
            tx_id,
            existing_category
        )
        return {"status": "ignored", "reason": "already categorized"}

    raw_cats = await firefly.get_categories()
    valid_categories = [c["attributes"]["name"] for c in raw_cats] if raw_cats else None

    prediction = await asyncio.to_thread(
        service.categorize,
        tx_obj,
        valid_categories=valid_categories
    )

    if not prediction:
        logger.info("[WEBHOOK] No prediction available for transaction %s; skipping.", tx_id)
        return {"status": "ignored", "reason": "no prediction"}

    auto_approve_threshold = float(os.getenv("AUTO_APPROVE_THRESHOLD", "0"))
    if auto_approve_threshold <= 0:
        logger.info(
            "[WEBHOOK] Auto-approve disabled (AUTO_APPROVE_THRESHOLD=%s). Suggested '%s'.",
            auto_approve_threshold,
            prediction.category.name
        )
        return {"status": "ignored", "reason": "auto-approve disabled"}

    if prediction.confidence < auto_approve_threshold:
        logger.info(
            "[WEBHOOK] Confidence %.2f below threshold %.2f for transaction %s; suggested '%s'.",
            prediction.confidence,
            auto_approve_threshold,
            tx_id,
            prediction.category.name
        )
        return {"status": "ignored", "reason": "low confidence"}

    if tx_id == "unknown":
        logger.warning("[WEBHOOK] Missing transaction ID; cannot update Firefly.")
        return {"status": "ignored", "reason": "missing transaction id"}

    auto_tags = _get_env_tags("AUTO_APPROVE_TAGS")
    tags_payload = _merge_tags(existing_tags, auto_tags) if auto_tags else existing_tags
    success = await firefly.update_transaction(
        tx_id,
        prediction.category.name,
        tags=tags_payload
    )
    if success:
        await asyncio.to_thread(service.learn, tx_obj, prediction.category)
        logger.info(
            "[WEBHOOK] Auto-categorized transaction %s as '%s' (confidence %.2f).",
            tx_id,
            prediction.category.name,
            prediction.confidence
        )
        return {"status": "updated"}

    logger.warning(
        "[WEBHOOK] Failed to update transaction %s with category '%s'.",
        tx_id,
        prediction.category.name
    )
    return {"status": "failed"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=get_logging_config())
