"""R-GEN-03 / FR-CAR-03 — live energy dashboard from TimescaleDB or demo memory."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.demo.memory_store import memory_store
from app.ingestion.freshness import check_freshness, freshness_to_dict, raise_alert_if_needed
from app.repositories import sensors as sensor_repo
from app.schemas import EnergyDashboardOut, EnergyHistoryPoint, EnergyHistoryOut
from app.services.carbon import compute_scopes

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _dashboard_from_reading(plant_code: str, reading, *, stream_status: str, age: float) -> EnergyDashboardOut:
    scopes = compute_scopes(
        fuel_gas_flow_km3h=float(reading.fuel_gas_flow_km3h or 0),
        steam_flow_tonh=float(reading.steam_flow_tonh or 0),
        electricity_power_mw=float(reading.electricity_power_mw or 0),
        feed_flow_tonh=float(reading.feed_flow_tonh or 1),
        duration_hours=1.0,
        plant_code=plant_code,
    )
    ts = reading.time
    if getattr(ts, "tzinfo", None) is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return EnergyDashboardOut(
        plant_code=plant_code,
        as_of=ts,
        electricity_power_mw=reading.electricity_power_mw,
        fuel_gas_flow_km3h=reading.fuel_gas_flow_km3h,
        steam_flow_tonh=reading.steam_flow_tonh,
        feed_flow_tonh=reading.feed_flow_tonh,
        reactor_temp_c=getattr(reading, "reactor_temp_c", None),
        pressure_bar=getattr(reading, "pressure_bar", None),
        energy_intensity_kgoe_ton=reading.energy_intensity_kgoe_ton,
        carbon_emission_kgco2_ton=reading.carbon_emission_kgco2_ton,
        carbon_intensity_kgco2_ton=scopes.carbon_intensity_kgco2_ton,
        energy_efficiency_percent=reading.energy_efficiency_percent,
        stream_status=stream_status,  # type: ignore[arg-type]
        data_age_seconds=age,
        factors_version=scopes.factors_version,
        scope1_kgco2=scopes.scope1_kgco2,
        scope2_kgco2=scopes.scope2_kgco2,
        source=getattr(reading, "source", None),
        quality=getattr(reading, "quality", None),
    )


def _memory_dashboard(plant_code: str) -> EnergyDashboardOut | None:
    reading = memory_store.latest(plant_code)
    if reading is None:
        return None
    age = max(0.0, (datetime.now(timezone.utc) - reading.time).total_seconds())
    stale = get_settings().stale_data_seconds
    stream = "ok" if age <= stale else "stale"
    return _dashboard_from_reading(plant_code, reading, stream_status=stream, age=age)


@router.get("/energy", response_model=EnergyDashboardOut)
async def energy_dashboard(
    plant_code: str = Query(default="olefin"),
    db: AsyncSession = Depends(get_db),
) -> EnergyDashboardOut:
    settings = get_settings()
    if settings.allow_demo_memory():
        mem = _memory_dashboard(plant_code)
        if mem is not None:
            return mem

    try:
        latest = await sensor_repo.get_latest_reading(db, plant_code)
    except Exception:  # noqa: BLE001
        latest = None

    if latest is None:
        if settings.allow_demo_memory():
            mem = _memory_dashboard(plant_code)
            if mem is not None:
                return mem
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No persisted readings for '{plant_code}'. "
                + (
                    "Plant Connect mode is on — start OPC producer/consumer."
                    if settings.plant_connect
                    else "Start demo feeder (`make demo-feeder`) or Kafka producer/consumer."
                )
            ),
        )

    _plant, reading = latest
    freshness = await check_freshness(db, plant_code)
    if freshness.status != "ok":
        await raise_alert_if_needed(db, freshness)

    return _dashboard_from_reading(
        plant_code,
        reading,
        stream_status=freshness.status,
        age=freshness.age_seconds or 0.0,
    )


@router.get("/energy/history", response_model=EnergyHistoryOut)
async def energy_history(
    plant_code: str = Query(default="olefin"),
    minutes: int = Query(default=15, ge=1, le=1440),
    db: AsyncSession = Depends(get_db),
) -> EnergyHistoryOut:
    settings = get_settings()
    rows = []
    use_memory = settings.allow_demo_memory()
    if not use_memory:
        try:
            rows = await sensor_repo.get_history(db, plant_code, minutes=minutes)
        except Exception:  # noqa: BLE001
            rows = []

    source_rows = []
    if use_memory:
        source_rows = memory_store.history(plant_code, minutes=minutes)
    if not source_rows:
        source_rows = rows
    if not source_rows and use_memory:
        source_rows = memory_store.history(plant_code, minutes=minutes)
    points: list[EnergyHistoryPoint] = []
    for r in source_rows:
        ts = r.time if getattr(r.time, "tzinfo", None) else r.time.replace(tzinfo=timezone.utc)
        fuel = float(getattr(r, "fuel_gas_flow_km3h", None) or 0)
        steam = float(getattr(r, "steam_flow_tonh", None) or 0)
        power = float(getattr(r, "electricity_power_mw", None) or 0)
        feed = float(getattr(r, "feed_flow_tonh", None) or 1)
        scopes = compute_scopes(
            fuel_gas_flow_km3h=fuel,
            steam_flow_tonh=steam,
            electricity_power_mw=power,
            feed_flow_tonh=feed,
            duration_hours=1.0,
            plant_code=plant_code,
        )
        points.append(
            EnergyHistoryPoint(
                time=ts,
                electricity_power_mw=getattr(r, "electricity_power_mw", None),
                fuel_gas_flow_km3h=getattr(r, "fuel_gas_flow_km3h", None),
                steam_flow_tonh=getattr(r, "steam_flow_tonh", None),
                feed_flow_tonh=getattr(r, "feed_flow_tonh", None),
                reactor_temp_c=getattr(r, "reactor_temp_c", None),
                pressure_bar=getattr(r, "pressure_bar", None),
                energy_intensity_kgoe_ton=getattr(r, "energy_intensity_kgoe_ton", None),
                carbon_emission_kgco2_ton=getattr(r, "carbon_emission_kgco2_ton", None),
                carbon_intensity_kgco2_ton=scopes.carbon_intensity_kgco2_ton,
                energy_efficiency_percent=getattr(r, "energy_efficiency_percent", None),
                scope1_kgco2=scopes.scope1_kgco2,
                scope2_kgco2=scopes.scope2_kgco2,
            )
        )

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
    settings = get_settings()
    if settings.allow_demo_memory():
        reading = memory_store.latest(plant_code)
        if reading is not None:
            age = max(0.0, (datetime.now(timezone.utc) - reading.time).total_seconds())
            st = "ok" if age <= settings.stale_data_seconds else "stale"
            return {"plant_code": plant_code, "status": st, "age_seconds": age, "source": "memory"}

    try:
        status_obj = await check_freshness(db, plant_code)
        if status_obj.status != "ok":
            await raise_alert_if_needed(db, status_obj)
        return freshness_to_dict(status_obj)
    except Exception:  # noqa: BLE001
        if not settings.allow_demo_memory():
            raise HTTPException(status_code=404, detail="No freshness data") from None
        reading = memory_store.latest(plant_code)
        if reading is None:
            raise HTTPException(status_code=404, detail="No freshness data") from None
        age = max(0.0, (datetime.now(timezone.utc) - reading.time).total_seconds())
        st = "ok" if age <= settings.stale_data_seconds else "stale"
        return {"plant_code": plant_code, "status": st, "age_seconds": age, "source": "memory"}
