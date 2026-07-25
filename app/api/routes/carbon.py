"""FR-CAR-01 / FR-CAR-02 / FR-CAR-03 / R-GEN-04 — carbon & sustainability APIs."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.carbon.factors import get_emission_factors
from app.carbon.market import sync_carbon_market
from app.carbon.reports import generate_and_persist_report, list_reports
from app.api.deps import require_action
from app.core.config import get_settings
from app.db.models import CarbonReport, Plant
from app.db.session import get_db
from app.repositories import sensors as sensor_repo
from app.schemas import (
    CarbonFactorOut,
    CarbonMarketSyncOut,
    CarbonReportOut,
    CarbonScopeOut,
    GenerateReportRequest,
    GenerateReportResponse,
)
from app.services.carbon import compute_scopes

router = APIRouter(prefix="/carbon", tags=["carbon"])


@router.get("/factors", response_model=list[CarbonFactorOut])
async def list_factors() -> list[CarbonFactorOut]:
    factors = get_emission_factors()
    return [
        CarbonFactorOut(
            plant_code=f.plant_code,
            natural_gas_kgco2_per_m3=f.natural_gas_kgco2_per_m3,
            steam_kgco2_per_ton=f.steam_kgco2_per_ton,
            electricity_kgco2_per_kwh=f.electricity_kgco2_per_kwh,
            version=f.version,
            source=f.source,
            notes=f.notes,
        )
        for f in factors.values()
    ]


@router.get("/scopes", response_model=CarbonScopeOut)
async def carbon_scopes(
    plant_code: str = Query(default="olefin"),
    period_type: str = Query(
        default="instant", pattern="^(instant|daily|monthly|yearly)$"
    ),
    db: AsyncSession = Depends(get_db),
) -> CarbonScopeOut:
    """
    Instant: compute from latest sensor reading with per-plant IPCC factors.
    daily/monthly/yearly: prefer persisted carbon_reports; else estimate from live snapshot.
    """
    if period_type == "instant":
        latest = await sensor_repo.get_latest_reading(db, plant_code)
        if latest is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No sensor readings for '{plant_code}'",
            )
        _, reading = latest
        scopes = compute_scopes(
            fuel_gas_flow_km3h=float(reading.fuel_gas_flow_km3h or 0),
            steam_flow_tonh=float(reading.steam_flow_tonh or 0),
            electricity_power_mw=float(reading.electricity_power_mw or 0),
            feed_flow_tonh=float(reading.feed_flow_tonh or 1),
            duration_hours=1.0,
            plant_code=plant_code,
        )
        return CarbonScopeOut(
            plant_code=plant_code,
            period_type="instant",
            scope1_kgco2=scopes.scope1_kgco2,
            scope2_kgco2=scopes.scope2_kgco2,
            total_kgco2=scopes.total_kgco2,
            carbon_intensity_kgco2_ton=scopes.carbon_intensity_kgco2_ton,
            product_ton=scopes.product_ton,
            factors_version=scopes.factors_version,
        )

    reports = await list_reports(
        db, plant_code=plant_code, period_type=period_type, limit=1  # type: ignore[arg-type]
    )
    if reports:
        report, code = reports[0]
        return CarbonScopeOut(
            plant_code=code,
            period_type=period_type,  # type: ignore[arg-type]
            scope1_kgco2=report.scope1_kgco2,
            scope2_kgco2=report.scope2_kgco2,
            total_kgco2=report.scope1_kgco2 + report.scope2_kgco2,
            carbon_intensity_kgco2_ton=report.carbon_intensity_kgco2_ton,
            product_ton=report.product_ton,
            factors_version=report.factors_version,
            report_id=report.id,
            period_start=report.period_start,
            period_end=report.period_end,
        )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=(
            f"No {period_type} report for '{plant_code}'. "
            "POST /api/v1/carbon/reports/generate first."
        ),
    )


@router.post("/reports/generate", response_model=GenerateReportResponse)
async def generate_report(
    body: GenerateReportRequest,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_action("operate")),
) -> GenerateReportResponse:
    settings = get_settings()
    export_dir = Path(settings.carbon_reports_export_dir)
    if not export_dir.is_absolute():
        export_dir = Path(__file__).resolve().parents[3] / export_dir

    generated = []
    for plant_code in body.plant_codes:
        for period in body.period_types:
            result = await generate_and_persist_report(
                db,
                plant_code,
                period,
                completed_only=body.completed_only,
                export_dir=export_dir,
            )
            if result is None:
                continue
            generated.append(
                CarbonReportOut(
                    id=result.report.id,
                    plant_code=result.plant_code,
                    period_type=result.report.period_type,  # type: ignore[arg-type]
                    period_start=result.report.period_start,
                    period_end=result.report.period_end,
                    scope1_kgco2=result.report.scope1_kgco2,
                    scope2_kgco2=result.report.scope2_kgco2,
                    total_kgco2=result.report.scope1_kgco2 + result.report.scope2_kgco2,
                    carbon_intensity_kgco2_ton=result.report.carbon_intensity_kgco2_ton,
                    product_ton=result.report.product_ton,
                    sample_count=result.report.sample_count,
                    factors_version=result.report.factors_version,
                    created_at=result.report.created_at,
                )
            )

    return GenerateReportResponse(
        generated=len(generated),
        reports=generated,
        message="Reports generated and persisted to carbon_reports",
    )


@router.get("/reports", response_model=list[CarbonReportOut])
async def get_reports(
    plant_code: str | None = None,
    period_type: Literal["daily", "monthly", "yearly"] | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[CarbonReportOut]:
    rows = await list_reports(
        db, plant_code=plant_code, period_type=period_type, limit=limit
    )
    return [
        CarbonReportOut(
            id=report.id,
            plant_code=code,
            period_type=report.period_type,  # type: ignore[arg-type]
            period_start=report.period_start,
            period_end=report.period_end,
            scope1_kgco2=report.scope1_kgco2,
            scope2_kgco2=report.scope2_kgco2,
            total_kgco2=report.scope1_kgco2 + report.scope2_kgco2,
            carbon_intensity_kgco2_ton=report.carbon_intensity_kgco2_ton,
            product_ton=report.product_ton,
            sample_count=report.sample_count,
            factors_version=report.factors_version,
            created_at=report.created_at,
        )
        for report, code in rows
    ]


@router.get("/reports/{report_id}/download")
async def download_report(
    report_id: int,
    format: Literal["json", "csv"] = Query(default="json"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    result = await db.execute(
        select(CarbonReport, Plant.code)
        .join(Plant, Plant.id == CarbonReport.plant_id)
        .where(CarbonReport.id == report_id)
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found")
    report, plant_code = row

    payload = {
        "id": report.id,
        "plant_code": plant_code,
        "period_type": report.period_type,
        "period_start": report.period_start.isoformat(),
        "period_end": report.period_end.isoformat(),
        "scope1_kgco2": report.scope1_kgco2,
        "scope2_kgco2": report.scope2_kgco2,
        "total_kgco2": report.scope1_kgco2 + report.scope2_kgco2,
        "carbon_intensity_kgco2_ton": report.carbon_intensity_kgco2_ton,
        "product_ton": report.product_ton,
        "sample_count": report.sample_count,
        "factors_version": report.factors_version,
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }

    filename = f"{plant_code}_{report.period_type}_{report.id}.{format}"
    if format == "json":
        return Response(
            content=json.dumps(payload, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(payload.keys()))
    writer.writeheader()
    writer.writerow(payload)
    return PlainTextResponse(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/market/sync", response_model=CarbonMarketSyncOut)
async def market_sync(
    plant_code: str | None = None,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_action("operate")),
) -> CarbonMarketSyncOut:
    result = await sync_carbon_market(db, plant_code=plant_code)
    return CarbonMarketSyncOut(
        status=result.status,
        synced_at=result.synced_at,
        registry=result.registry,
        message=result.message,
        reports_synced=result.reports_synced,
        batch_id=result.batch_id,
        payload_path=result.payload_path,
    )


@router.get("/kpi/intensity")
async def carbon_intensity_kpi(
    plant_code: str = Query(default="olefin"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """FR-CAR-03 — carbon intensity KPI for main dashboard."""
    latest = await sensor_repo.get_latest_reading(db, plant_code)
    live = None
    if latest is not None:
        _, reading = latest
        live = compute_scopes(
            fuel_gas_flow_km3h=float(reading.fuel_gas_flow_km3h or 0),
            steam_flow_tonh=float(reading.steam_flow_tonh or 0),
            electricity_power_mw=float(reading.electricity_power_mw or 0),
            feed_flow_tonh=float(reading.feed_flow_tonh or 1),
            duration_hours=1.0,
            plant_code=plant_code,
        )

    daily_reports = await list_reports(db, plant_code=plant_code, period_type="daily", limit=1)
    daily = None
    if daily_reports:
        report, _ = daily_reports[0]
        daily = {
            "carbon_intensity_kgco2_ton": report.carbon_intensity_kgco2_ton,
            "scope1_kgco2": report.scope1_kgco2,
            "scope2_kgco2": report.scope2_kgco2,
            "period_start": report.period_start.isoformat(),
            "period_end": report.period_end.isoformat(),
            "report_id": report.id,
        }

    return {
        "plant_code": plant_code,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "live_carbon_intensity_kgco2_ton": live.carbon_intensity_kgco2_ton if live else None,
        "live_scope1_kgco2": live.scope1_kgco2 if live else None,
        "live_scope2_kgco2": live.scope2_kgco2 if live else None,
        "daily_report": daily,
        "kpi": "carbon_intensity",
    }
