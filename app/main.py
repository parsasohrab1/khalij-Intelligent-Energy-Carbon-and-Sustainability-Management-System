"""iEMS FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.deps import require_action
from app.api.routes import (
    alerts,
    auth,
    carbon,
    dashboard,
    health,
    ingestion,
    operator,
    ops,
    optimization,
    prediction,
    settings as settings_routes,
)
from app.core.config import get_settings
from app.core.state import close_db, close_redis, init_db, init_redis
from app.observability.metrics import MetricsMiddleware, mount_metrics
from app.security.headers import SecurityHeadersMiddleware

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_DASHBOARD_HTML = _STATIC_DIR / "dashboard.html"
_feeder_task: asyncio.Task | None = None
_feeder_worker = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _feeder_task, _feeder_worker
    settings = get_settings()
    try:
        await init_db(settings)
    except Exception as exc:  # noqa: BLE001
        logger.warning("TimescaleDB init skipped/failed: %s", exc.__class__.__name__)
    try:
        await init_redis(settings)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis init skipped/failed: %s", exc.__class__.__name__)

    if settings.should_run_demo_feeder():
        from app.demo.feeder import DemoFeeder

        _feeder_worker = DemoFeeder(settings)
        _feeder_task = asyncio.create_task(_feeder_worker.run_forever())
        logger.info(
            "Inline demo feeder started (demo_feeder=%s app_env=%s)",
            settings.demo_feeder,
            settings.app_env,
        )
    elif settings.plant_connect:
        logger.info(
            "Plant Connect mode ON — demo feeder disabled; OPC endpoint=%s source=%s",
            settings.opc_ua_endpoint or "(missing)",
            settings.ingestion_source,
        )

    yield

    if _feeder_worker is not None:
        await _feeder_worker.stop()
        _feeder_worker = None
    if _feeder_task is not None:
        _feeder_task.cancel()
        try:
            await _feeder_task
        except asyncio.CancelledError:
            pass
        _feeder_task = None

    try:
        from app.ingestion.opcua_session import close_plant_session

        await close_plant_session()
    except Exception:  # noqa: BLE001
        logger.exception("OPC session close failed")

    await close_redis()
    await close_db()


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="Khalij iEMS",
        description=(
            "Intelligent Energy, Carbon & Sustainability Management System — "
            "real-time monitoring, ML forecasting, and Scope 1/2 carbon reporting "
            "for olefin & PTA petrochemical units."
        ),
        version=__version__,
        lifespan=lifespan,
    )
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(MetricsMiddleware)
    mount_metrics(application)

    read_deps = [Depends(require_action("read"))] if settings.auth_enforce else []
    write_deps = [Depends(require_action("operate"))] if settings.auth_enforce else []
    predict_deps = [Depends(require_action("predict"))] if settings.auth_enforce else []

    application.include_router(health.router)
    application.include_router(auth.router, prefix="/api/v1")
    application.include_router(ops.router, prefix="/api/v1", dependencies=read_deps)
    application.include_router(settings_routes.router, prefix="/api/v1")
    application.include_router(operator.router, prefix="/api/v1", dependencies=read_deps)
    application.include_router(dashboard.router, prefix="/api/v1", dependencies=read_deps)
    application.include_router(ingestion.router, prefix="/api/v1", dependencies=write_deps)
    application.include_router(alerts.router, prefix="/api/v1", dependencies=read_deps)
    application.include_router(prediction.router, prefix="/api/v1", dependencies=predict_deps)
    application.include_router(optimization.router, prefix="/api/v1", dependencies=write_deps)
    application.include_router(carbon.router, prefix="/api/v1", dependencies=read_deps)

    application.mount(
        "/static",
        StaticFiles(directory=str(_STATIC_DIR)),
        name="static",
    )

    @application.get("/dashboard", include_in_schema=False)
    async def live_dashboard_page() -> FileResponse:
        return FileResponse(_DASHBOARD_HTML, media_type="text/html; charset=utf-8")

    @application.get("/")
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/dashboard")

    @application.get("/api", include_in_schema=False)
    async def api_info() -> dict:
        return {
            "app": settings.app_name,
            "version": __version__,
            "docs": "/docs",
            "dashboard": "/dashboard",
            "units": settings.unit_code_list,
            "auth_enforce": settings.auth_enforce,
            "oidc_enabled": settings.oidc_enabled,
            "site_code": settings.site_code,
            "demo_feeder": settings.should_run_demo_feeder(),
            "plant_connect": settings.plant_connect,
            "ingestion_source": settings.ingestion_source,
        }

    return application


app = create_app()


def run() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_debug and settings.app_env == "development",
    )


if __name__ == "__main__":
    run()
