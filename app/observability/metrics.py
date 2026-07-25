"""Prometheus metrics endpoint and HTTP instrumentation (Phase 5)."""

from __future__ import annotations

import time
from collections.abc import Callable

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

    REQUESTS = Counter(
        "iems_http_requests_total",
        "Total HTTP requests",
        ["method", "path", "status"],
    )
    LATENCY = Histogram(
        "iems_http_request_duration_seconds",
        "HTTP request latency",
        ["method", "path"],
        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5),
    )
    APP_UP = Gauge("iems_app_up", "API process up")
    APP_UP.set(1)
    PROM_AVAILABLE = True
except ImportError:  # pragma: no cover
    PROM_AVAILABLE = False


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not PROM_AVAILABLE:
            return await call_next(request)
        start = time.perf_counter()
        response = await call_next(request)
        path = request.url.path
        # Avoid high-cardinality path params explosion for ids
        if "/recommendations/" in path:
            path = "/api/v1/optimization/recommendations/{id}"
        elif "/reports/" in path and path.endswith("/download"):
            path = "/api/v1/carbon/reports/{id}/download"
        LATENCY.labels(request.method, path).observe(time.perf_counter() - start)
        REQUESTS.labels(request.method, path, str(response.status_code)).inc()
        return response


def mount_metrics(app: FastAPI) -> None:
    if not PROM_AVAILABLE:
        return

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
