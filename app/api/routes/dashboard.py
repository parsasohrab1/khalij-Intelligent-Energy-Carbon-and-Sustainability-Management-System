"""R-GEN-03 / FR-CAR-03 — live energy dashboard from TimescaleDB."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.ingestion.freshness import check_freshness, freshness_to_dict, raise_alert_if_needed
from app.repositories import sensors as sensor_repo
from app.schemas import EnergyDashboardOut, EnergyHistoryPoint, EnergyHistoryOut
from app.services.carbon import compute_scopes

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/energy", response_model=EnergyDashboardOut)
async def energy_dashboard(
    plant_code: str = Query(default="olefin"),
    db: AsyncSession = Depends(get_db),
) -> EnergyDashboardOut:
    latest = await sensor_repo.get_latest_reading(db, plant_code)
    if latest is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No persisted readings for '{plant_code}'. "
                "Start the Phase-1 producer/consumer pipeline first."
            ),
        )

    _plant, reading = latest
    scopes = compute_scopes(
        fuel_gas_flow_km3h=float(reading.fuel_gas_flow_km3h or 0),
        steam_flow_tonh=float(reading.steam_flow_tonh or 0),
        electricity_power_mw=float(reading.electricity_power_mw or 0),
        feed_flow_tonh=float(reading.feed_flow_tonh or 1),
        duration_hours=1.0,
        plant_code=plant_code,
    )
    freshness = await check_freshness(db, plant_code)
    if freshness.status != "ok":
        await raise_alert_if_needed(db, freshness)

    ts = reading.time
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    return EnergyDashboardOut(
        plant_code=plant_code,
        as_of=ts,
        electricity_power_mw=reading.electricity_power_mw,
        fuel_gas_flow_km3h=reading.fuel_gas_flow_km3h,
        steam_flow_tonh=reading.steam_flow_tonh,
        feed_flow_tonh=reading.feed_flow_tonh,
        energy_intensity_kgoe_ton=reading.energy_intensity_kgoe_ton,
        carbon_emission_kgco2_ton=reading.carbon_emission_kgco2_ton,
        carbon_intensity_kgco2_ton=scopes.carbon_intensity_kgco2_ton,
        energy_efficiency_percent=reading.energy_efficiency_percent,
        stream_status=freshness.status,
        data_age_seconds=freshness.age_seconds,
        factors_version=scopes.factors_version,
        scope1_kgco2=scopes.scope1_kgco2,
        scope2_kgco2=scopes.scope2_kgco2,
    )


@router.get("/energy/history", response_model=EnergyHistoryOut)
async def energy_history(
    plant_code: str = Query(default="olefin"),
    minutes: int = Query(default=15, ge=1, le=1440),
    db: AsyncSession = Depends(get_db),
) -> EnergyHistoryOut:
    rows = await sensor_repo.get_history(db, plant_code, minutes=minutes)
    points = [
        EnergyHistoryPoint(
            time=r.time if r.time.tzinfo else r.time.replace(tzinfo=timezone.utc),
            electricity_power_mw=r.electricity_power_mw,
            energy_intensity_kgoe_ton=r.energy_intensity_kgoe_ton,
            carbon_emission_kgco2_ton=r.carbon_emission_kgco2_ton,
            energy_efficiency_percent=r.energy_efficiency_percent,
        )
        for r in rows
    ]
    return EnergyHistoryOut(
        plant_code=plant_code,
        minutes=minutes,
        count=len(points),
        points=points,
        generated_at=datetime.now(timezone.utc),
    )


@router.get("/freshness")
async def stream_freshness(
    plant_code: str = Query(default="olefin"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    status_obj = await check_freshness(db, plant_code)
    if status_obj.status != "ok":
        await raise_alert_if_needed(db, status_obj)
    return freshness_to_dict(status_obj)
