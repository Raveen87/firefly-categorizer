import json
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
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

# Load environment variables
load_dotenv()

# Setup logging
setup_logging()
logger = get_logger(__name__)

# Global service instance
service: CategorizerService | None = None
firefly: FireflyClient | None = None
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "web/templates"))

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global service, firefly
    # Initialize service on startup
    logger.info("Initializing services...")

    # Check Environment Variables
    if not os.getenv("FIREFLY_URL") or not os.getenv("FIREFLY_TOKEN"):
        logger.warning("FIREFLY_URL or FIREFLY_TOKEN not set. Firefly integration will be disabled.")

    if not os.getenv("OPENAI_API_KEY"):
        logger.info("OPENAI_API_KEY not set. OpenAI integration will be disabled.")

    service = CategorizerService(data_dir=".")
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
    total_fetched = 0

    async for page_txs, _ in firefly.yield_transactions():
        total_fetched += len(page_txs)

        for t_data in page_txs:
            attrs = t_data.get("attributes", {}).get("transactions", [{}])[0]
            desc = attrs.get("description", "")
            amount = float(attrs.get("amount", 0.0))
            curr = attrs.get("currency_code", "EUR")
            date_str = attrs.get("date", "")
            category_name = attrs.get("category_name")

            # Skip uncategorized transactions
            if not category_name:
                skipped_count += 1
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

            # Train the models
            service.learn(tx_obj, Category(name=category_name))
            trained_count += 1

        logger.info(f"[TRAIN] Processed page. Total trained so far: {trained_count}")

    logger.info(f"[TRAIN] Complete! Trained: {trained_count}, Skipped (no category): {skipped_count}")

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
        if not service or not firefly:
            yield f"data: {json.dumps({'stage': 'error', 'message': 'Service not initialized'})}\n\n"
            return

        trained_count = 0
        skipped_count = 0
        total_fetched = 0
        total_estimate = 0

        # Notify start
        yield f"data: {json.dumps({'stage': 'start'})}\n\n"

        async for page_txs, meta in firefly.yield_transactions():
            # Update total estimate from metadata
            if total_estimate == 0:
                total_estimate = meta.get("total", 0)

            total_fetched += len(page_txs)

            # Process this page
            for t_data in page_txs:
                attrs = t_data.get("attributes", {}).get("transactions", [{}])[0]
                desc = attrs.get("description", "")
                amount = float(attrs.get("amount", 0.0))
                curr = attrs.get("currency_code", "EUR")
                date_str = attrs.get("date", "")
                category_name = attrs.get("category_name")

                if not category_name:
                    skipped_count += 1
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

                service.learn(tx_obj, Category(name=category_name))
                trained_count += 1

            # Yield progress after each page
            percent = round(total_fetched / total_estimate * 100, 1) if total_estimate > 0 else 0
            yield f"data: {json.dumps({
                'stage': 'processing',
                'trained': trained_count,
                'skipped': skipped_count,
                'fetched': total_fetched,
                'total': total_estimate,
                'percent': percent
            })}\n\n"

        # Stage Complete
        yield f"data: {json.dumps({
            'stage': 'complete',
            'trained': trained_count,
            'skipped': skipped_count,
            'total_fetched': total_fetched
        })}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")

@app.post("/clear-models")
async def clear_models() -> dict[str, str]:
    if not service:
        raise HTTPException(status_code=500, detail="Service not initialized")

    service.clear_models()
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
        success = await firefly.update_transaction(req.transaction_id, req.category.name)
        firefly_update_status = "success" if success else "failed"

    return {
        "status": "success",
        "message": "Learned new transaction",
        "firefly_update": firefly_update_status,
        "source": source
    }

@app.get("/api/transactions")
async def get_transactions(
    start_date: str | None = None,
    end_date: str | None = None,
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

        # Get auto-approve threshold from env (0 = disabled)
        auto_approve_threshold = float(os.getenv("AUTO_APPROVE_THRESHOLD", "0"))

        for t_data in raw_txs:
            attrs = t_data.get("attributes", {}).get("transactions", [{}])[0]
            desc = attrs.get("description", "")
            amount = float(attrs.get("amount", 0.0))
            curr = attrs.get("currency_code", "EUR")
            date_str = attrs.get("date", "")
            existing_cat = attrs.get("category_name") # May be None or string
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
                prediction = service.categorize(tx_obj, valid_categories=category_list if category_list else None)

                # Auto-approve if confidence exceeds threshold
                if prediction and auto_approve_threshold > 0 and prediction.confidence >= auto_approve_threshold:
                    logger.info(
                        f"[AUTO-APPROVE] Transaction {tx_id}: '{prediction.category.name}' "
                        f"(confidence: {prediction.confidence:.2f} >= {auto_approve_threshold})"
                    )
                    # Update Firefly
                    success = await firefly.update_transaction(tx_id, prediction.category.name)
                    if success:
                        # Learn from this auto-approval
                        service.learn(tx_obj, prediction.category)
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
                "auto_approved": auto_approved,
                "raw_obj": tx_obj.model_dump_json() # For JS to pick up
            })

    return {
        "transactions": transactions_display,
        "pagination": pagination
    }

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, start_date: str | None = None, end_date: str | None = None) -> HTMLResponse:
    category_list = []
    if firefly:
        raw_cats = await firefly.get_categories()
        category_list = sorted([c["attributes"]["name"] for c in raw_cats])

    # Just setup defaults for inputs, data fetched via JS
    if not start_date:
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")

    return templates.TemplateResponse("index.html", {
        "request": request,
        "categories": category_list,
        "start_date": start_date,
        "end_date": end_date
    })

@app.get("/help", response_class=HTMLResponse)
async def help_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("help.html", {
        "request": request
    })

@app.get("/train-page", response_class=HTMLResponse)
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
    data = await request.json()
    logger.info(f"Webhook received: {data}")
    return {"status": "received"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=get_logging_config())
