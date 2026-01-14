import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from firefly_categorizer.api.routes import categorize, pages, training, transactions, webhook
from firefly_categorizer.core import settings
from firefly_categorizer.integration.firefly import FireflyClient
from firefly_categorizer.logger import get_logger, setup_logging
from firefly_categorizer.manager import CategorizerService
from firefly_categorizer.services.categorization import CategorizationPipeline
from firefly_categorizer.services.training import TrainingManager

logger = get_logger(__name__)


def create_app() -> FastAPI:
    setup_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        logger.info("Initializing services...")
        settings.log_environment()

        if not os.getenv("FIREFLY_URL") or not os.getenv("FIREFLY_TOKEN"):
            logger.warning("FIREFLY_URL or FIREFLY_TOKEN not set. Firefly integration will be disabled.")

        if not os.getenv("OPENAI_API_KEY"):
            logger.info("OPENAI_API_KEY not set. OpenAI integration will be disabled.")

        service = CategorizerService(data_dir=settings.DATA_DIR)
        firefly = FireflyClient()
        training_manager = TrainingManager(service=service, firefly=firefly, page_size=settings.TRAINING_PAGE_SIZE)
        pipeline = CategorizationPipeline(service=service, firefly=firefly)

        app.state.service = service
        app.state.firefly = firefly
        app.state.training_manager = training_manager
        app.state.pipeline = pipeline

        logger.info("Services initialized.")
        yield
        logger.info("Service shutting down.")

    app = FastAPI(title="Firefly Categorizer", lifespan=lifespan)

    static_dir = os.path.join(os.path.dirname(__file__), "web/static")
    if not os.path.exists(static_dir):
        os.makedirs(static_dir)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    app.include_router(categorize.router)
    app.include_router(training.router)
    app.include_router(transactions.router)
    app.include_router(pages.router)
    app.include_router(webhook.router)

    return app


app = create_app()
