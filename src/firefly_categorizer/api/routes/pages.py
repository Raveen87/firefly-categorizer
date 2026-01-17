import os
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from firefly_categorizer.api.dependencies import get_firefly_optional
from firefly_categorizer.core import configuration
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


@router.get("/config", response_class=HTMLResponse)
async def config_page(request: Request, saved: bool = False) -> HTMLResponse:
    context = configuration.build_config_context()
    status = "Configuration saved." if saved else None
    return templates.TemplateResponse(
        "config.html",
        {
            "request": request,
            "status": status,
            "errors": {},
            **context,
        },
    )


@router.post("/config", response_class=HTMLResponse)
async def save_config(request: Request) -> Response:
    form = await request.form()
    payload = {key: str(value) for key, value in form.items()}
    errors, updates = configuration.apply_config_updates(payload)
    if errors:
        context = configuration.build_config_context(field_errors=errors)
        return templates.TemplateResponse(
            "config.html",
            {
                "request": request,
                "status": None,
                "errors": errors,
                **context,
            },
        )
    configuration.apply_runtime_updates(request.app, updates)
    return RedirectResponse(url="/config?saved=1", status_code=303)
