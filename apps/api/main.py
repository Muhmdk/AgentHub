"""FastAPI composition root for the AgentHub control plane."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from apps.api.config import Settings, load_settings
from apps.api.errors import register_error_handlers
from apps.api.logging import configure_logging
from apps.api.middleware import correlation_middleware
from packages.contracts.health import HealthResponse, VersionResponse

logger = logging.getLogger("agenthub.api")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an application with explicit, testable dependencies."""
    app_settings = settings or load_settings()
    configure_logging(app_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("service_started")
        yield
        logger.info("service_stopped")

    app = FastAPI(
        title="AgentHub API",
        version=app_settings.version,
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.middleware("http")(correlation_middleware)
    register_error_handlers(app)

    @app.get("/health/live", response_model=HealthResponse, tags=["health"])
    async def liveness() -> HealthResponse:
        return HealthResponse(status="ok", service=app_settings.service_name)

    @app.get("/health/ready", response_model=HealthResponse, tags=["health"])
    async def readiness() -> HealthResponse:
        return HealthResponse(status="ready", service=app_settings.service_name)

    @app.get("/version", response_model=VersionResponse, tags=["metadata"])
    async def service_version() -> VersionResponse:
        return VersionResponse(
            service=app_settings.service_name,
            version=app_settings.version,
            environment=app_settings.environment,
        )

    return app


app = create_app()
