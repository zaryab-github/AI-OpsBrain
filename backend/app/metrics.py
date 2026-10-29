"""Prometheus metrics for the API process, exposed at /metrics (internal network + bearer token)."""

from __future__ import annotations

import hmac
import time

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from sqlalchemy import select

from app.config import get_config
from app.db import session_factory
from app.models import SelfmonCheck

REGISTRY = CollectorRegistry()
HTTP_REQUESTS = Counter("obs_http_requests_total", "HTTP requests", ["method", "route", "status"], registry=REGISTRY)
HTTP_LATENCY = Histogram("obs_http_request_duration_seconds", "HTTP request latency", ["method", "route"],
                         buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10), registry=REGISTRY)
BUILD_INFO = Gauge("obs_build_info", "Build information", ["version"], registry=REGISTRY)
SELFMON_STATUS = Gauge("obs_selfmon_status", "Self-monitoring check: 0 ok, 1 warn, 2 crit", ["check", "source"],
                       registry=REGISTRY)
_SEVERITY = {"ok": 0, "warn": 1, "crit": 2}


def install(app: FastAPI) -> None:
    BUILD_INFO.labels(version=get_config().version).set(1)

    @app.middleware("http")
    async def _measure(request: Request, call_next):  # type: ignore[no-untyped-def]
        start = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        template = getattr(route, "path", "unmatched")
        HTTP_REQUESTS.labels(request.method, template, str(response.status_code)).inc()
        HTTP_LATENCY.labels(request.method, template).observe(time.perf_counter() - start)
        return response

    @app.get("/metrics", include_in_schema=False)
    def metrics(request: Request) -> Response:
        supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not supplied or not hmac.compare_digest(supplied, get_config().metrics_token):
            return Response(status_code=401, content="unauthorized", headers={"WWW-Authenticate": "Bearer"})
        with session_factory()() as db:
            for row in db.execute(select(SelfmonCheck)).scalars():
                SELFMON_STATUS.labels(row.name, row.source).set(_SEVERITY.get(row.status, 2))
        return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
