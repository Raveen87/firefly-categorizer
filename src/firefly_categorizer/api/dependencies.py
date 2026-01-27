from fastapi import HTTPException, Request

from firefly_categorizer.integration.firefly import FireflyClient
from firefly_categorizer.manager import CategorizerService
from firefly_categorizer.services.categorization import CategorizationPipeline
from firefly_categorizer.services.training import TrainingManager


def get_service(request: Request) -> CategorizerService:
    service = getattr(request.app.state, "service", None)
    if not service:
        raise HTTPException(status_code=500, detail="Service not initialized")
    return service


def get_service_optional(request: Request) -> CategorizerService | None:
    return getattr(request.app.state, "service", None)


def get_firefly_optional(request: Request) -> FireflyClient | None:
    return getattr(request.app.state, "firefly", None)


def get_firefly(request: Request) -> FireflyClient:
    firefly = getattr(request.app.state, "firefly", None)
    if not firefly:
        raise HTTPException(status_code=500, detail="Firefly not configured")
    return firefly


def get_training_manager(request: Request) -> TrainingManager:
    manager = getattr(request.app.state, "training_manager", None)
    if not manager:
        raise HTTPException(status_code=500, detail="Service not initialized")
    return manager


def get_pipeline(request: Request) -> CategorizationPipeline:
    pipeline = getattr(request.app.state, "pipeline", None)
    if not pipeline:
        raise HTTPException(status_code=500, detail="Service not initialized")
    return pipeline


def get_pipeline_optional(request: Request) -> CategorizationPipeline | None:
    return getattr(request.app.state, "pipeline", None)
