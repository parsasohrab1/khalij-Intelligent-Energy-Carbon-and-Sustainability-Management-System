"""E11 — enterprise ops status, sites, SLO targets."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_action
from app.core.config import get_settings
from app.db.session import get_db
from app.services.oidc import oidc_status
from app.services.sites import get_site, list_sites

router = APIRouter(prefix="/ops", tags=["ops"])


@router.get("/status")
async def ops_status() -> dict[str, Any]:
    """E11 exit checklist snapshot for AUTH_ENFORCE + monitoring readiness."""
    cfg = get_settings()
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "app_env": cfg.app_env,
        "auth_enforce": cfg.auth_enforce,
        "oidc": oidc_status(cfg),
        "site_code": cfg.site_code,
        "plant_connect": cfg.plant_connect,
        "trusted_mode": cfg.trusted_mode_active,
        "slo": {
            "availability_target": 0.9995,
            "availability_probe": "/readyz",
            "p95_latency_seconds": 3.0,
            "mape_target_percent": 5.0,
        },
        "monitoring": {
            "prometheus_job": "iems-api",
            "alert_group": "iems-reliability",
            "note": "Enable with make up-monitoring / make up-prod",
        },
        "ha": {
            "api_profile": "ha (api-b on :8001)",
            "db": "single TimescaleDB + logical backups",
            "kafka": "single broker (document RF=1 limit)",
        },
    }


@router.get("/sites")
async def sites(
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_action("read")),
) -> list[dict[str, Any]]:
    rows = await list_sites(db)
    return [
        {
            "code": s.code,
            "name": s.name,
            "region": s.region,
            "plants": s.plants,
        }
        for s in rows
    ]


@router.get("/sites/{code}")
async def site_detail(
    code: str,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_action("read")),
) -> dict[str, Any]:
    site = await get_site(db, code)
    if site is None:
        raise HTTPException(status_code=404, detail=f"Site '{code}' not found")
    return {
        "code": site.code,
        "name": site.name,
        "region": site.region,
        "plants": site.plants,
    }
