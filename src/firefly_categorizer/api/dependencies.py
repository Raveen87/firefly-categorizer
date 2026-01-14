from fastapi import HTTPException, Request

from firefly_categorizer.integration.firefly import FireflyClient
from firefly_categorizer.manager import CategorizerService
from firefly_categorizer.services.categorization import CategorizationPipeline
from firefly_categorizer.services.training import TrainingManager


def get_service(request: Request) -> CategorizerService:
    service = request.app.state.service
    if not service:
        raise HTTPException(status_code=500, detail="Service not initialized")
    return service


def get_service_optional(request: Request) -> CategorizerService | None:
    return request.app.state.service


def get_firefly_optional(request: Request) -> FireflyClient | None:
    return request.app.state.firefly


def get_firefly(request: Request) -> FireflyClient:
    firefly = request.app.state.firefly
    if not firefly:
        raise HTTPException(status_code=500, detail="Firefly not configured")
    return firefly


def get_training_manager(request: Request) -> TrainingManager:
    manager = request.app.state.training_manager
    if not manager:
        raise HTTPException(status_code=500, detail="Service not initialized")
    return manager


def get_pipeline(request: Request) -> CategorizationPipeline:
    pipeline = request.app.state.pipeline
    if not pipeline:
        raise HTTPException(status_code=500, detail="Service not initialized")
    return pipeline


def get_pipeline_optional(request: Request) -> CategorizationPipeline | None:
    return request.app.state.pipeline
