"""FR-CAR-02 — carbon market / registry integration."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import CarbonMarketSync, CarbonReport, Plant

logger = logging.getLogger(__name__)


@dataclass
class MarketSyncResult:
    status: str
    synced_at: datetime
    registry: str
    message: str
    reports_synced: int
    batch_id: str
    payload_path: str | None = None
    external_ref: str | None = None


def _staging_dir(settings: Settings) -> Path:
    path = Path(settings.carbon_market_staging_dir)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    path.mkdir(parents=True, exist_ok=True)
    return path


async def build_registry_payload(
    session: AsyncSession,
    *,
    plant_code: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    stmt = (
        select(CarbonReport, Plant.code)
        .join(Plant, Plant.id == CarbonReport.plant_id)
        .order_by(CarbonReport.period_start.desc())
        .limit(limit)
    )
    if plant_code:
        stmt = stmt.where(Plant.code == plant_code)
    rows = (await session.execute(stmt)).all()
    return [
        {
            "plant_code": code,
            "period_type": report.period_type,
            "period_start": report.period_start.isoformat(),
            "period_end": report.period_end.isoformat(),
            "scope1_kgco2": report.scope1_kgco2,
            "scope2_kgco2": report.scope2_kgco2,
            "total_kgco2": report.scope1_kgco2 + report.scope2_kgco2,
            "carbon_intensity_kgco2_ton": report.carbon_intensity_kgco2_ton,
            "product_ton": report.product_ton,
            "factors_version": report.factors_version,
            "report_id": report.id,
        }
        for report, code in rows
    ]


async def sync_carbon_market(
    session: AsyncSession,
    *,
    plant_code: str | None = None,
    settings: Settings | None = None,
) -> MarketSyncResult:
    """
    Stage Scope 1/2 reports for an external carbon registry.

    If CARBON_MARKET_API_URL is set, POSTs the payload; otherwise writes a
    local staging JSON file for offline / partner exchange.
    """
    cfg = settings or get_settings()
    now = datetime.now(timezone.utc)
    batch_id = str(uuid.uuid4())
    payload = await build_registry_payload(session, plant_code=plant_code)
    registry = cfg.carbon_market_registry_name
    staging = _staging_dir(cfg)
    file_path = staging / f"market_sync_{batch_id}.json"
    envelope = {
        "batch_id": batch_id,
        "registry": registry,
        "synced_at": now.isoformat(),
        "plant_filter": plant_code,
        "reports": payload,
    }
    file_path.write_text(json.dumps(envelope, indent=2), encoding="utf-8")

    external_ref: str | None = None
    status = "staged"
    message = f"Staged {len(payload)} report(s) at {file_path.as_posix()}"

    if cfg.carbon_market_api_url:
        try:
            headers = {}
            if cfg.carbon_market_api_token:
                headers["Authorization"] = f"Bearer {cfg.carbon_market_api_token}"
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    cfg.carbon_market_api_url,
                    json=envelope,
                    headers=headers or None,
                )
                response.raise_for_status()
                body = response.json() if response.content else {}
                external_ref = str(
                    body.get("id") or body.get("reference") or response.status_code
                )
                status = "synced"
                message = f"Posted {len(payload)} report(s) to {registry}"
        except Exception as exc:  # noqa: BLE001
            logger.exception("Carbon market API sync failed")
            status = "error"
            message = (
                f"API sync failed ({exc.__class__.__name__}); "
                f"payload kept at {file_path}"
            )

    if external_ref:
        message = f"{message} (ref={external_ref})"

    record = CarbonMarketSync(
        batch_id=batch_id,
        plant_code=plant_code,
        status=status,
        registry=registry,
        message=message,
        reports_synced=len(payload),
        payload_path=str(file_path),
        synced_at=now,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)

    return MarketSyncResult(
        status=status,
        synced_at=now,
        registry=registry,
        message=message,
        reports_synced=len(payload),
        batch_id=batch_id,
        payload_path=str(file_path),
        external_ref=external_ref,
    )
