"""iEMS FastAPI application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.deps import require_action
from app.api.routes import (
    alerts,
    auth,
    carbon,
    dashboard,
    health,
    ingestion,
    optimization,
    prediction,
    settings as settings_routes,
)
from app.core.config import get_settings
from app.core.state import close_db, close_redis, init_db, init_redis
from app.observability.metrics import MetricsMiddleware, mount_metrics
from app.security.headers import SecurityHeadersMiddleware


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    try:
        await init_db(settings)
    except Exception:  # noqa: BLE001
        pass
    try:
        await init_redis(settings)
    except Exception:  # noqa: BLE001
        pass
    yield
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
    application.include_router(settings_routes.router, prefix="/api/v1")
    application.include_router(dashboard.router, prefix="/api/v1", dependencies=read_deps)
    application.include_router(ingestion.router, prefix="/api/v1", dependencies=write_deps)
    application.include_router(alerts.router, prefix="/api/v1", dependencies=read_deps)
    application.include_router(prediction.router, prefix="/api/v1", dependencies=predict_deps)
    application.include_router(optimization.router, prefix="/api/v1", dependencies=write_deps)
    application.include_router(carbon.router, prefix="/api/v1", dependencies=read_deps)

    @application.get("/")
    async def root() -> dict:
        return {
            "app": settings.app_name,
            "version": __version__,
            "docs": "/docs",
            "units": settings.unit_code_list,
            "auth_enforce": settings.auth_enforce,
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
