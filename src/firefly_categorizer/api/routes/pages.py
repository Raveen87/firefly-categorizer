import os
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from firefly_categorizer.api.dependencies import get_firefly_optional
from firefly_categorizer.integration.firefly import FireflyClient
from firefly_categorizer.services.firefly_data import fetch_category_names, is_all_scope

router = APIRouter()

templates_dir = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "web", "templates")
)
templates = Jinja2Templates(directory=templates_dir)


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    firefly: Annotated[FireflyClient | None, Depends(get_firefly_optional)],
    start_date: str | None = None,
    end_date: str | None = None,
    scope: str | None = None,
) -> HTMLResponse:
    category_list = []
    if firefly:
        category_list = await fetch_category_names(firefly, sort=True)

    if not start_date:
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")

    scope_mode = "all" if is_all_scope(scope) else "range"

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "categories": category_list,
            "start_date": start_date,
            "end_date": end_date,
            "scope": scope_mode,
        },
    )


@router.get("/help", response_class=HTMLResponse)
async def help_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("help.html", {"request": request})


@router.get("/train", response_class=HTMLResponse)
async def train_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("train.html", {"request": request})
