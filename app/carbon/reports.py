"""Period helpers and automated Scope 1/2 report generation (R-GEN-04)."""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.carbon.assurance import ensure_e10_schema
from app.carbon.factors import factors_for
from app.carbon.scope3 import compute_scope3
from app.db.models import CarbonReport, Plant, SensorReading
from app.services.carbon import CarbonBreakdown, compute_scopes_from_integrals

logger = logging.getLogger(__name__)

PeriodType = Literal["daily", "monthly", "yearly"]


@dataclass
class PeriodWindow:
    period_type: PeriodType
    start: datetime
    end: datetime


def period_window(
    period_type: PeriodType,
    *,
    reference: datetime | None = None,
    completed_only: bool = True,
) -> PeriodWindow:
    """
    Return [start, end) for the reporting period.
    If completed_only, returns the last fully completed day/month/year.
    """
    ref = reference or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)

    if period_type == "daily":
        end = ref.replace(hour=0, minute=0, second=0, microsecond=0)
        if not completed_only:
            end = end + timedelta(days=1)
        start = end - timedelta(days=1)
        return PeriodWindow("daily", start, end)

    if period_type == "monthly":
        first_of_month = ref.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = first_of_month if completed_only else _add_months(first_of_month, 1)
        start = _add_months(end, -1)
        return PeriodWindow("monthly", start, end)

    # yearly
    first_of_year = ref.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    end = first_of_year if completed_only else first_of_year.replace(year=first_of_year.year + 1)
    start = end.replace(year=end.year - 1)
    return PeriodWindow("yearly", start, end)


def _add_months(dt: datetime, months: int) -> datetime:
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    return dt.replace(year=year, month=month, day=1)


@dataclass
class AggregateTotals:
    sample_count: int
    fuel_gas_km3: float
    steam_ton: float
    electricity_mwh: float
    product_ton: float
    mean_fuel_gas_flow_km3h: float
    mean_steam_flow_tonh: float
    mean_electricity_power_mw: float
    mean_feed_flow_tonh: float


async def aggregate_sensor_period(
    session: AsyncSession,
    plant_code: str,
    start: datetime,
    end: datetime,
) -> AggregateTotals | None:
    """
    Integrate 1 Hz (or sub-second) samples over [start, end).

    Each sample is treated as lasting until the next sample, capped at 1s default
    spacing via mean-rate × duration when sample density is high.
    """
    plant_id = (
        await session.execute(select(Plant.id).where(Plant.code == plant_code))
    ).scalar_one_or_none()
    if plant_id is None:
        raise ValueError(f"Unknown plant_code: {plant_code}")

    stmt: Select[Any] = select(
        func.count(SensorReading.time),
        func.avg(SensorReading.fuel_gas_flow_km3h),
        func.avg(SensorReading.steam_flow_tonh),
        func.avg(SensorReading.electricity_power_mw),
        func.avg(SensorReading.feed_flow_tonh),
    ).where(
        SensorReading.plant_id == plant_id,
        SensorReading.time >= start,
        SensorReading.time < end,
    )
    row = (await session.execute(stmt)).one()
    count = int(row[0] or 0)
    if count == 0:
        return None

    mean_fuel = float(row[1] or 0)
    mean_steam = float(row[2] or 0)
    mean_power = float(row[3] or 0)
    mean_feed = float(row[4] or 0)
    duration_hours = max((end - start).total_seconds() / 3600.0, 1e-9)

    return AggregateTotals(
        sample_count=count,
        fuel_gas_km3=mean_fuel * duration_hours,
        steam_ton=mean_steam * duration_hours,
        electricity_mwh=mean_power * duration_hours,
        product_ton=mean_feed * duration_hours,
        mean_fuel_gas_flow_km3h=mean_fuel,
        mean_steam_flow_tonh=mean_steam,
        mean_electricity_power_mw=mean_power,
        mean_feed_flow_tonh=mean_feed,
    )


@dataclass
class GeneratedReport:
    report: CarbonReport
    breakdown: CarbonBreakdown
    plant_code: str
    aggregates: AggregateTotals
    factors_version: str


async def generate_and_persist_report(
    session: AsyncSession,
    plant_code: str,
    period_type: PeriodType,
    *,
    reference: datetime | None = None,
    completed_only: bool = True,
    export_dir: Path | None = None,
) -> GeneratedReport | None:
    window = period_window(period_type, reference=reference, completed_only=completed_only)
    aggregates = await aggregate_sensor_period(session, plant_code, window.start, window.end)
    if aggregates is None:
        logger.warning(
            "No sensor data for %s %s [%s → %s)",
            plant_code,
            period_type,
            window.start.isoformat(),
            window.end.isoformat(),
        )
        return None

    breakdown = compute_scopes_from_integrals(
        fuel_gas_km3=aggregates.fuel_gas_km3,
        steam_ton=aggregates.steam_ton,
        electricity_mwh=aggregates.electricity_mwh,
        product_ton=aggregates.product_ton,
        plant_code=plant_code,
    )
    s3 = compute_scope3(
        plant_code=plant_code,
        fuel_gas_km3=aggregates.fuel_gas_km3,
        product_ton=aggregates.product_ton,
    )
    ef = factors_for(plant_code)

    await ensure_e10_schema(session)

    plant_id = (
        await session.execute(select(Plant.id).where(Plant.code == plant_code))
    ).scalar_one()

    existing = (
        await session.execute(
            select(CarbonReport).where(
                CarbonReport.plant_id == plant_id,
                CarbonReport.period_start == window.start,
                CarbonReport.period_type == period_type,
            )
        )
    ).scalar_one_or_none()

    scope3_detail = {
        "cat3_fuel_upstream_kgco2": s3.cat3_fuel_upstream_kgco2,
        "cat1_purchased_goods_kgco2": s3.cat1_purchased_goods_kgco2,
        "cat5_waste_kgco2": s3.cat5_waste_kgco2,
        "factors_version": s3.factors_version,
        **s3.detail,
    }

    if existing is not None and (getattr(existing, "assurance_status", None) or "draft") == "locked":
        logger.warning(
            "Skipping regenerate for locked report id=%s plant=%s",
            existing.id,
            plant_code,
        )
        return GeneratedReport(
            report=existing,
            breakdown=breakdown,
            plant_code=plant_code,
            aggregates=aggregates,
            factors_version=ef.version,
        )

    if existing is None:
        report = CarbonReport(
            plant_id=plant_id,
            period_start=window.start,
            period_end=window.end,
            period_type=period_type,
            scope1_kgco2=breakdown.scope1_kgco2,
            scope2_kgco2=breakdown.scope2_kgco2,
            scope3_kgco2=s3.total_kgco2,
            scope3_detail_json=json.dumps(scope3_detail),
            carbon_intensity_kgco2_ton=breakdown.carbon_intensity_kgco2_ton,
            product_ton=breakdown.product_ton,
            sample_count=aggregates.sample_count,
            factors_version=ef.version,
            assurance_status="draft",
            created_at=datetime.now(timezone.utc),
        )
        session.add(report)
    else:
        report = existing
        report.period_end = window.end
        report.scope1_kgco2 = breakdown.scope1_kgco2
        report.scope2_kgco2 = breakdown.scope2_kgco2
        report.scope3_kgco2 = s3.total_kgco2
        report.scope3_detail_json = json.dumps(scope3_detail)
        report.carbon_intensity_kgco2_ton = breakdown.carbon_intensity_kgco2_ton
        report.product_ton = breakdown.product_ton
        report.sample_count = aggregates.sample_count
        report.factors_version = ef.version
        if not getattr(report, "assurance_status", None):
            report.assurance_status = "draft"

    await session.commit()
    await session.refresh(report)

    if export_dir is not None:
        export_dir.mkdir(parents=True, exist_ok=True)
        _write_exports(export_dir, plant_code, report, breakdown, aggregates)

    return GeneratedReport(
        report=report,
        breakdown=breakdown,
        plant_code=plant_code,
        aggregates=aggregates,
        factors_version=ef.version,
    )


def _write_exports(
    export_dir: Path,
    plant_code: str,
    report: CarbonReport,
    breakdown: CarbonBreakdown,
    aggregates: AggregateTotals,
) -> None:
    stamp = report.period_start.strftime("%Y%m%d")
    base = f"{plant_code}_{report.period_type}_{stamp}_report_{report.id}"
    payload = {
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
        "aggregates": asdict(aggregates),
        "breakdown": {
            "scope1_kgco2": breakdown.scope1_kgco2,
            "scope2_kgco2": breakdown.scope2_kgco2,
            "carbon_intensity_kgco2_ton": breakdown.carbon_intensity_kgco2_ton,
            "product_ton": breakdown.product_ton,
            "factors_version": breakdown.factors_version,
        },
    }
    json_path = export_dir / f"{base}.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    csv_path = export_dir / f"{base}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "plant_code",
                "period_type",
                "period_start",
                "period_end",
                "scope1_kgco2",
                "scope2_kgco2",
                "total_kgco2",
                "carbon_intensity_kgco2_ton",
                "product_ton",
                "sample_count",
                "factors_version",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
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
            }
        )


async def list_reports(
    session: AsyncSession,
    *,
    plant_code: str | None = None,
    period_type: PeriodType | None = None,
    limit: int = 50,
) -> list[tuple[CarbonReport, str]]:
    stmt = (
        select(CarbonReport, Plant.code)
        .join(Plant, Plant.id == CarbonReport.plant_id)
        .order_by(CarbonReport.period_start.desc())
        .limit(limit)
    )
    if plant_code:
        stmt = stmt.where(Plant.code == plant_code)
    if period_type:
        stmt = stmt.where(CarbonReport.period_type == period_type)
    rows = (await session.execute(stmt)).all()
    return [(r, code) for r, code in rows]
