"""Persist and query sensor readings in TimescaleDB (R-GEN-02, E6)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Plant, SensorReading


async def get_plant_id(session: AsyncSession, plant_code: str) -> int | None:
    result = await session.execute(select(Plant.id).where(Plant.code == plant_code))
    return result.scalar_one_or_none()


def _quality_detail_str(payload: dict[str, Any]) -> str | None:
    detail = payload.get("quality_detail")
    if detail is None:
        return None
    if isinstance(detail, str):
        return detail
    return json.dumps(detail)


def _apply_fields(row: SensorReading, payload: dict[str, Any]) -> None:
    row.electricity_power_mw = payload.get("electricity_power_mw")
    row.fuel_gas_flow_km3h = payload.get("fuel_gas_flow_km3h")
    row.steam_flow_tonh = payload.get("steam_flow_tonh")
    row.feed_flow_tonh = payload.get("feed_flow_tonh")
    row.reactor_temp_c = payload.get("reactor_temp_c")
    row.pressure_bar = payload.get("pressure_bar")
    row.energy_intensity_kgoe_ton = payload.get("energy_intensity_kgoe_ton")
    row.carbon_emission_kgco2_ton = payload.get("carbon_emission_kgco2_ton")
    row.energy_efficiency_percent = payload.get("energy_efficiency_percent")
    row.source = payload.get("source")
    row.quality = payload.get("quality")
    row.quality_detail = _quality_detail_str(payload)


async def upsert_reading(session: AsyncSession, payload: dict[str, Any]) -> SensorReading:
    plant_code = payload["plant_code"]
    plant_id = await get_plant_id(session, plant_code)
    if plant_id is None:
        raise ValueError(f"Unknown plant_code: {plant_code}")

    ts = payload["time"]
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))

    reading = SensorReading(time=ts, plant_id=plant_id)
    _apply_fields(reading, payload)
    session.add(reading)
    try:
        await session.commit()
        await session.refresh(reading)
        return reading
    except Exception:
        await session.rollback()
        existing = await session.execute(
            select(SensorReading).where(
                SensorReading.time == ts, SensorReading.plant_id == plant_id
            )
        )
        row = existing.scalar_one_or_none()
        if row is None:
            raise
        _apply_fields(row, payload)
        await session.commit()
        await session.refresh(row)
        return row


async def get_latest_reading(
    session: AsyncSession, plant_code: str
) -> tuple[Plant, SensorReading] | None:
    result = await session.execute(
        select(Plant, SensorReading)
        .join(SensorReading, SensorReading.plant_id == Plant.id)
        .where(Plant.code == plant_code)
        .order_by(SensorReading.time.desc())
        .limit(1)
    )
    row = result.first()
    if row is None:
        return None
    return row[0], row[1]


async def get_history(
    session: AsyncSession,
    plant_code: str,
    *,
    minutes: int = 15,
    limit: int = 900,
) -> list[SensorReading]:
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    result = await session.execute(
        select(SensorReading)
        .join(Plant, Plant.id == SensorReading.plant_id)
        .where(Plant.code == plant_code, SensorReading.time >= since)
        .order_by(SensorReading.time.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def reading_age_seconds(session: AsyncSession, plant_code: str) -> float | None:
    latest = await get_latest_reading(session, plant_code)
    if latest is None:
        return None
    _, reading = latest
    ts = reading.time
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds()


async def ensure_unique_index(session: AsyncSession) -> None:
    """Ensure conflict target exists for duplicate-second protection + E6 columns."""
    await session.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_sensor_readings_time_plant "
            "ON sensor_readings (time, plant_id)"
        )
    )
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS stream_alerts (
                id           SERIAL PRIMARY KEY,
                plant_code   TEXT NOT NULL,
                alert_type   TEXT NOT NULL,
                message      TEXT NOT NULL,
                age_seconds  DOUBLE PRECISION,
                created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                resolved_at  TIMESTAMPTZ
            )
            """
        )
    )
    for col, typ in (
        ("source", "TEXT"),
        ("quality", "TEXT"),
        ("quality_detail", "TEXT"),
    ):
        await session.execute(
            text(
                f"ALTER TABLE sensor_readings ADD COLUMN IF NOT EXISTS {col} {typ}"
            )
        )
    await session.commit()
