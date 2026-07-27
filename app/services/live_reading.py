"""Resolve a live plant reading: demo memory → DB → OPC/simulator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.demo.memory_store import MemoryReading, memory_store
from app.ingestion.opcua_client import read_opcua_plant
from app.repositories import sensors as sensor_repo
from app.services.physics import enrich_reading


@dataclass
class LiveReading:
    time: datetime
    plant_code: str
    electricity_power_mw: float
    fuel_gas_flow_km3h: float
    steam_flow_tonh: float
    feed_flow_tonh: float
    reactor_temp_c: float
    pressure_bar: float | None
    energy_intensity_kgoe_ton: float
    carbon_emission_kgco2_ton: float | None
    energy_efficiency_percent: float
    source: str
    quality: str | None = None

    def as_memory(self) -> MemoryReading:
        return MemoryReading(
            time=self.time,
            plant_code=self.plant_code,
            electricity_power_mw=self.electricity_power_mw,
            fuel_gas_flow_km3h=self.fuel_gas_flow_km3h,
            steam_flow_tonh=self.steam_flow_tonh,
            feed_flow_tonh=self.feed_flow_tonh,
            reactor_temp_c=self.reactor_temp_c,
            pressure_bar=self.pressure_bar,
            energy_intensity_kgoe_ton=self.energy_intensity_kgoe_ton,
            carbon_emission_kgco2_ton=self.carbon_emission_kgco2_ton,
            energy_efficiency_percent=self.energy_efficiency_percent,
            source=self.source,
            quality=self.quality,
        )


def _from_payload(plant_code: str, payload: dict[str, Any], *, source: str) -> LiveReading:
    base = {
        "electricity_power_mw": float(payload.get("electricity_power_mw") or 15.0),
        "fuel_gas_flow_km3h": float(payload.get("fuel_gas_flow_km3h") or 100.0),
        "steam_flow_tonh": float(payload.get("steam_flow_tonh") or 30.0),
        "feed_flow_tonh": float(payload.get("feed_flow_tonh") or 100.0),
        "reactor_temp_c": float(payload.get("reactor_temp_c") or 400.0),
    }
    derived = enrich_reading(**base)
    ts = payload.get("time") or datetime.now(timezone.utc)
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if getattr(ts, "tzinfo", None) is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return LiveReading(
        time=ts,
        plant_code=plant_code,
        pressure_bar=(
            float(payload["pressure_bar"])
            if payload.get("pressure_bar") is not None
            else None
        ),
        energy_intensity_kgoe_ton=float(
            payload.get("energy_intensity_kgoe_ton")
            or derived["energy_intensity_kgoe_ton"]
        ),
        carbon_emission_kgco2_ton=(
            float(payload["carbon_emission_kgco2_ton"])
            if payload.get("carbon_emission_kgco2_ton") is not None
            else derived.get("carbon_emission_kgco2_ton")
        ),
        energy_efficiency_percent=float(
            payload.get("energy_efficiency_percent")
            or derived["energy_efficiency_percent"]
        ),
        source=str(payload.get("source") or source),
        quality=payload.get("quality"),
        **base,
    )


def _from_memory(plant_code: str, reading: MemoryReading) -> LiveReading:
    return _from_payload(plant_code, reading.to_dict(), source=reading.source or "memory")


async def resolve_live_reading(
    session: AsyncSession | None,
    plant_code: str,
) -> LiveReading:
    settings = get_settings()
    if settings.allow_demo_memory():
        mem = memory_store.latest(plant_code)
        if mem is not None:
            return _from_memory(plant_code, mem)

    if session is not None:
        try:
            latest = await sensor_repo.get_latest_reading(session, plant_code)
        except Exception:  # noqa: BLE001
            latest = None
        if latest is not None:
            _, reading = latest
            return _from_payload(
                plant_code,
                {
                    "time": reading.time,
                    "electricity_power_mw": reading.electricity_power_mw,
                    "fuel_gas_flow_km3h": reading.fuel_gas_flow_km3h,
                    "steam_flow_tonh": reading.steam_flow_tonh,
                    "feed_flow_tonh": reading.feed_flow_tonh,
                    "reactor_temp_c": reading.reactor_temp_c,
                    "pressure_bar": reading.pressure_bar,
                    "energy_intensity_kgoe_ton": reading.energy_intensity_kgoe_ton,
                    "carbon_emission_kgco2_ton": reading.carbon_emission_kgco2_ton,
                    "energy_efficiency_percent": reading.energy_efficiency_percent,
                    "source": getattr(reading, "source", None) or "db",
                    "quality": getattr(reading, "quality", None),
                },
                source="db",
            )

    if settings.allow_demo_memory():
        mem = memory_store.latest(plant_code)
        if mem is not None:
            return _from_memory(plant_code, mem)

    snap = await read_opcua_plant(plant_code, settings)
    live = _from_payload(plant_code, snap, source=str(snap.get("source") or "simulator"))
    if settings.allow_demo_memory():
        memory_store.append({**snap, "plant_code": plant_code, "source": live.source})
    return live
