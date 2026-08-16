"""Dachik FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.config import Settings
from backend.app.database import Database
from backend.app.schemas import ErrorResponse, HealthResponse

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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["Accept", "Content-Type"],
    )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API error", exc_info=exc)
        payload = ErrorResponse(error="internal_server_error", detail="Unexpected error")
        return JSONResponse(status_code=500, content=payload.model_dump())

    @app.get("/health", response_model=HealthResponse, tags=["operations"])
    async def health() -> HealthResponse:
        return HealthResponse(version=APP_VERSION)

    return app


app = create_app()
