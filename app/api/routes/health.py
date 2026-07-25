"""Health, liveness, readiness — NFR-REL-01 monitoring hooks."""

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.core.config import get_settings
from app.core.state import state
from app.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    checks: dict[str, str] = {"api": "ok"}

    if state.engine is not None:
        try:
            async with state.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["timescaledb"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["timescaledb"] = f"error:{exc.__class__.__name__}"
    else:
        checks["timescaledb"] = "skipped"

    if state.redis is not None:
        try:
            pong = await state.redis.ping()
            checks["redis"] = "ok" if pong else "error"
        except Exception as exc:  # noqa: BLE001
            checks["redis"] = f"error:{exc.__class__.__name__}"
    else:
        checks["redis"] = "skipped"

    checks["kafka"] = settings.kafka_bootstrap_servers
    checks["mlflow"] = settings.mlflow_tracking_uri
    infra_ok = all(
        v in {"ok", "skipped"} or not v.startswith("error")
        for k, v in checks.items()
        if k in {"api", "timescaledb", "redis"}
    )
    health_status = "ok" if infra_ok else "degraded"

    return HealthResponse(
        status=health_status,  # type: ignore[arg-type]
        app=settings.app_name,
        env=settings.app_env,
        checks=checks,
    )


@router.get("/livez")
async def livez() -> dict[str, str]:
    """Kubernetes liveness — process is up."""
    return {"status": "alive"}


@router.get("/readyz")
async def readyz(response: Response) -> dict:
    """Kubernetes readiness — critical deps available."""
    body = await health()
    if body.status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": body.status, "checks": body.checks}
