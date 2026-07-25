"""Admin settings API — requires RBAC admin + TOTP (NFR-SEC-01)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import require_action, require_settings_admin
from app.core.config import get_settings
from app.services.auth import CurrentUser

router = APIRouter(prefix="/settings", tags=["settings"])


class RuntimeSettingsOut(BaseModel):
    app_env: str
    auth_enforce: bool
    stale_data_seconds: float
    unit_codes: list[str]
    ml_mape_target: float
    ml_max_latency_ms: float
    carbon_report_interval_seconds: int
    ingestion_rate_hz: float


class RuntimeSettingsUpdate(BaseModel):
    stale_data_seconds: float | None = Field(default=None, ge=1, le=3600)
    ml_mape_target: float | None = Field(default=None, ge=0.1, le=50)
    ml_max_latency_ms: float | None = Field(default=None, ge=100, le=30000)
    carbon_report_interval_seconds: int | None = Field(default=None, ge=30, le=86400)
    ingestion_rate_hz: float | None = Field(default=None, ge=0.1, le=10)


@router.get("", response_model=RuntimeSettingsOut)
async def get_settings_view(
    _user: CurrentUser = Depends(require_action("settings")),
) -> RuntimeSettingsOut:
    s = get_settings()
    return RuntimeSettingsOut(
        app_env=s.app_env,
        auth_enforce=s.auth_enforce,
        stale_data_seconds=s.stale_data_seconds,
        unit_codes=s.unit_code_list,
        ml_mape_target=s.ml_mape_target,
        ml_max_latency_ms=s.ml_max_latency_ms,
        carbon_report_interval_seconds=s.carbon_report_interval_seconds,
        ingestion_rate_hz=s.ingestion_rate_hz,
    )


@router.patch("", response_model=RuntimeSettingsOut)
async def patch_settings(
    body: RuntimeSettingsUpdate,
    _user: CurrentUser = Depends(require_settings_admin),
) -> RuntimeSettingsOut:
    """
    Mutate in-memory runtime settings (process-local).
    Production should persist via ConfigMap/Secret and rolling restart.
    """
    s = get_settings()
    if body.stale_data_seconds is not None:
        s.stale_data_seconds = body.stale_data_seconds
    if body.ml_mape_target is not None:
        s.ml_mape_target = body.ml_mape_target
    if body.ml_max_latency_ms is not None:
        s.ml_max_latency_ms = body.ml_max_latency_ms
    if body.carbon_report_interval_seconds is not None:
        s.carbon_report_interval_seconds = body.carbon_report_interval_seconds
    if body.ingestion_rate_hz is not None:
        s.ingestion_rate_hz = body.ingestion_rate_hz
    return await get_settings_view(_user)
