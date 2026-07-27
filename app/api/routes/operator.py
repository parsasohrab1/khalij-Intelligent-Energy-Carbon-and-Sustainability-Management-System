"""E7 — operator shift helpers (summary + CSV export without /docs)."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.demo.memory_store import memory_store
from app.ingestion.freshness import check_freshness, list_open_alerts
from app.repositories import sensors as sensor_repo
from app.services.carbon import compute_scopes

router = APIRouter(prefix="/operator", tags=["operator"])


async def _latest_snapshot(db: AsyncSession, plant_code: str) -> dict:
    settings = get_settings()
    reading = None
    source = "db"
    if settings.allow_demo_memory():
        mem = memory_store.latest(plant_code)
        if mem is not None:
            reading = mem
            source = "memory"
    if reading is None:
        try:
            latest = await sensor_repo.get_latest_reading(db, plant_code)
            if latest is not None:
                reading = latest[1]
        except Exception:  # noqa: BLE001
            reading = None
    if reading is None:
        return {"plant_code": plant_code, "available": False, "source": source}

    scopes = compute_scopes(
        fuel_gas_flow_km3h=float(getattr(reading, "fuel_gas_flow_km3h", 0) or 0),
        steam_flow_tonh=float(getattr(reading, "steam_flow_tonh", 0) or 0),
        electricity_power_mw=float(getattr(reading, "electricity_power_mw", 0) or 0),
        feed_flow_tonh=float(getattr(reading, "feed_flow_tonh", 1) or 1),
        duration_hours=1.0,
        plant_code=plant_code,
    )
    freshness = None
    try:
        freshness = await check_freshness(db, plant_code, settings)
    except Exception:  # noqa: BLE001
        freshness = None
    return {
        "plant_code": plant_code,
        "available": True,
        "source": getattr(reading, "source", source),
        "quality": getattr(reading, "quality", None),
        "as_of": getattr(reading, "time", None),
        "electricity_power_mw": getattr(reading, "electricity_power_mw", None),
        "fuel_gas_flow_km3h": getattr(reading, "fuel_gas_flow_km3h", None),
        "steam_flow_tonh": getattr(reading, "steam_flow_tonh", None),
        "feed_flow_tonh": getattr(reading, "feed_flow_tonh", None),
        "energy_intensity_kgoe_ton": getattr(reading, "energy_intensity_kgoe_ton", None),
        "energy_efficiency_percent": getattr(reading, "energy_efficiency_percent", None),
        "scope1_kgco2": scopes.scope1_kgco2,
        "scope2_kgco2": scopes.scope2_kgco2,
        "carbon_intensity_kgco2_ton": scopes.carbon_intensity_kgco2_ton,
        "stream_status": freshness.status if freshness else None,
        "data_age_seconds": freshness.age_seconds if freshness else None,
    }


@router.get("/shift-summary")
async def shift_summary(
    plant_code: str = Query(default="olefin"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """One-screen shift briefing for operators (E7)."""
    snap = await _latest_snapshot(db, plant_code)
    alerts = []
    try:
        alerts = await list_open_alerts(db, limit=20)
    except Exception:  # noqa: BLE001
        alerts = []
    open_alerts = [
        {
            "id": a.id,
            "plant_code": a.plant_code,
            "alert_type": a.alert_type,
            "message": a.message,
        }
        for a in alerts
        if a.plant_code == plant_code or True
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "plant": snap,
        "open_notifications": len(open_alerts),
        "notifications": open_alerts[:10],
        "checklist": [
            "Confirm live stream status is ok",
            "Acknowledge critical notifications",
            "Review optimization recommendations",
            "Export daily carbon CSV if required",
        ],
    }


@router.get("/shift-report.csv")
async def shift_report_csv(
    plant_code: str = Query(default="olefin"),
    db: AsyncSession = Depends(get_db),
) -> PlainTextResponse:
    """Excel-compatible CSV shift snapshot (E7 reporting without PDF stack)."""
    snap = await _latest_snapshot(db, plant_code)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["field", "value"])
    writer.writerow(["generated_at", datetime.now(timezone.utc).isoformat()])
    for key, value in snap.items():
        writer.writerow([key, value])
    filename = f"shift_report_{plant_code}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.csv"
    return PlainTextResponse(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
