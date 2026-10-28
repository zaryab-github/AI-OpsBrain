import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.routing import Match

from app import __version__, logging_setup
from app.api import audit_log, auth, roles, settings, system, users
from app.config import get_settings
from app.db import dispose_engine
from app.redis_client import close_redis

REQUESTS = Counter("opsbrain_api_requests_total", "API requests", ["method", "route", "status"])
LATENCY = Histogram("opsbrain_api_request_seconds", "API request latency", ["method", "route"])


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engine()
    await close_redis()


def _route_template(request: Request) -> str:
    for route in request.app.router.routes:
        if route.matches(request.scope)[0] == Match.FULL:
            return getattr(route, "path", "unmatched")
    return "unmatched"


def create_app() -> FastAPI:
    cfg = get_settings()
    logging_setup.configure(cfg.log_level)
    docs = cfg.env != "production"
    app = FastAPI(
        title="AI-OpsBrain API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs" if docs else None,
        openapi_url="/api/openapi.json" if docs else None,
        redoc_url=None,
    )

    @app.middleware("http")
    async def metrics_mw(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        route = _route_template(request)
        REQUESTS.labels(request.method, route, str(response.status_code)).inc()
        LATENCY.labels(request.method, route).observe(time.perf_counter() - start)
        response.headers["Cache-Control"] = "no-store"
        return response

    v1 = "/api/v1"
    app.include_router(system.health_router, prefix="/api")
    for r in (system.router, auth.router, users.router, roles.router, audit_log.router, settings.router):
        app.include_router(r, prefix=v1)
    # Reachable only on the internal network; Caddy refuses this path from outside.
    app.add_api_route("/api/metrics", lambda: Response(generate_latest(), media_type=CONTENT_TYPE_LATEST),
                      include_in_schema=False)
    return app


app = create_app()
