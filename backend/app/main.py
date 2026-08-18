"""Dachik FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.api import router as api_router
from backend.app.config import Settings
from backend.app.database import Database
from backend.app.schemas import ErrorResponse, HealthResponse
from backend.app.services import ConflictError, DomainError, NotFoundError
from collector.service import TEST_ENVIRONMENT, LaunchAgentManager, ServiceStatus

APP_VERSION = "0.1.0"
# Operational endpoints remain unversioned; future domain APIs belong under /api/v1.
API_V1_PREFIX = "/api/v1"
logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings()
    database = Database(resolved_settings.database_path)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        database.initialize()
        yield

    app = FastAPI(
        title="Dachik Local API",
        version=APP_VERSION,
        lifespan=lifespan,
    )
    app.state.database = database
    app.state.sensor_service_manager = (
        _InactiveServiceManager()
        if resolved_settings.runtime_environment == TEST_ENVIRONMENT
        else LaunchAgentManager(settings=resolved_settings)
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Accept", "Content-Type"],
    )
    app.include_router(api_router)

    @app.exception_handler(NotFoundError)
    async def not_found_handler(_: Request, exc: NotFoundError) -> JSONResponse:
        payload = ErrorResponse(error="not_found", detail=str(exc))
        return JSONResponse(status_code=404, content=payload.model_dump())

    @app.exception_handler(ConflictError)
    async def conflict_handler(_: Request, exc: ConflictError) -> JSONResponse:
        payload = ErrorResponse(error="conflict", detail=str(exc))
        return JSONResponse(status_code=409, content=payload.model_dump())

    @app.exception_handler(DomainError)
    async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
        payload = ErrorResponse(error="validation_error", detail=str(exc))
        return JSONResponse(status_code=422, content=payload.model_dump())

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API error", exc_info=exc)
        payload = ErrorResponse(error="internal_server_error", detail="Unexpected error")
        return JSONResponse(status_code=500, content=payload.model_dump())

    @app.get("/health", response_model=HealthResponse, tags=["operations"])
    async def health() -> HealthResponse:
        return HealthResponse(version=APP_VERSION)

    return app


class _InactiveServiceManager:
    def status(self) -> ServiceStatus:
        return ServiceStatus(
            installed=False,
            expected_to_run=False,
            process_running=False,
            state="stopped",
        )


app = create_app()
