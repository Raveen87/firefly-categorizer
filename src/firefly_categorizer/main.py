from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from models import Transaction, Category, CategorizationResult
from manager import CategorizerService
from integration.firefly import FireflyClient
from typing import List, Optional
import os
import uvicorn
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

# Global service instance
service: Optional[CategorizerService] = None
firefly: Optional[FireflyClient] = None
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "web/templates"))

@asynccontextmanager
async def lifespan(app: FastAPI):
    global service, firefly
    # Initialize service on startup
    print("Initializing services...")
    service = CategorizerService(data_dir=".")
    firefly = FireflyClient() # Will use env vars
    print("Services initialized.")
    yield
    print("Service shutting down.")

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

@app.post("/categorize", response_model=Optional[CategorizationResult])
async def categorize_transaction(req: CategorizeRequest):
    if not service:
        raise HTTPException(status_code=500, detail="Service not initialized")
    return service.categorize(req.transaction)

@app.post("/learn")
async def learn_transaction(req: LearnRequest):
    if not service:
        raise HTTPException(status_code=500, detail="Service not initialized")
    service.learn(req.transaction, req.category)
    return {"status": "success", "message": "Learned new transaction"}

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, start_date: str = None, end_date: str = None):
    transactions_display = []
    
    if firefly:
        # Default dates: last 30 days
        if not start_date:
            s_date = datetime.now() - timedelta(days=30)
            start_date_obj = s_date
            start_date = s_date.strftime("%Y-%m-%d")
        else:
            start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")

        if not end_date:
            e_date = datetime.now()
            end_date_obj = e_date
            end_date = e_date.strftime("%Y-%m-%d")
        else:
            end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")

        raw_txs = await firefly.get_transactions(start_date=start_date_obj, end_date=end_date_obj)
        
        for t_data in raw_txs:
            attrs = t_data.get("attributes", {}).get("transactions", [{}])[0]
            desc = attrs.get("description", "")
            amount = float(attrs.get("amount", 0.0))
            curr = attrs.get("currency_code", "EUR")
            date_str = attrs.get("date", "")
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
            
            # Predict
            prediction = service.categorize(tx_obj)
            
            transactions_display.append({
                "id": t_data.get("id"),
                "date_formatted": dt.strftime("%Y-%m-%d"),
                "description": desc,
                "amount": amount,
                "currency": curr,
                "prediction": prediction,
                "raw_obj": tx_obj.model_dump_json() # For JS to pick up
            })
            
    return templates.TemplateResponse("index.html", {
        "request": request,
        "transactions": transactions_display,
        "start_date": start_date,
        "end_date": end_date
    })

# Firefly Webhook Endpoint
@app.post("/webhook/firefly")
async def firefly_webhook(request: Request):
    """
    Handle Firefly III Webhook.
    """
    data = await request.json()
    print(f"Webhook received: {data}")
    return {"status": "received"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
