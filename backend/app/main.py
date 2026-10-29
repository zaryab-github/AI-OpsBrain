"""Application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app import metrics
from app.config import get_config
from app.db import get_engine
from app.errors import install_error_handlers
from app.logging_setup import configure_logging
from app.routers import audit_log, auth, roles, settings_api, system, users

log = logging.getLogger("obs.api")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    config = get_config()  # fails fast on missing / weak secrets
    get_engine()
    log.info("api started", extra={"version": config.version, "env": config.env})
    yield


def create_app() -> FastAPI:
    configure_logging()
    config = get_config()
    app = FastAPI(
        title="AI Centralized Observability Platform",
        version=config.version,
        lifespan=lifespan,
        docs_url=None if config.is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if config.is_production else "/api/openapi.json",
    )
    install_error_handlers(app)
    metrics.install(app)

    @app.middleware("http")
    async def _no_store(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    for module in (auth, users, roles, audit_log, settings_api, system):
        app.include_router(module.router, prefix="/api/v1")
    return app


app = create_app()
