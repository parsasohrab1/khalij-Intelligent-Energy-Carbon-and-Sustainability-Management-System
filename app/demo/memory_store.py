"""In-memory live stream for Kafka-less demos (R-GEN-01/03)."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any


@dataclass
class MemoryReading:
    time: datetime
    plant_code: str
    electricity_power_mw: float | None = None
    fuel_gas_flow_km3h: float | None = None
    steam_flow_tonh: float | None = None
    feed_flow_tonh: float | None = None
    reactor_temp_c: float | None = None
    pressure_bar: float | None = None
    energy_intensity_kgoe_ton: float | None = None
    carbon_emission_kgco2_ton: float | None = None
    energy_efficiency_percent: float | None = None
    source: str | None = None
    quality: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["time"] = self.time.isoformat()
        return d


class MemoryStore:
    def __init__(self, maxlen: int = 3600) -> None:
        self._lock = Lock()
        self._series: dict[str, deque[MemoryReading]] = defaultdict(
            lambda: deque(maxlen=maxlen)
        )

    def append(self, payload: dict[str, Any]) -> MemoryReading:
        ts = payload["time"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        reading = MemoryReading(
            time=ts,
            plant_code=payload["plant_code"],
            electricity_power_mw=payload.get("electricity_power_mw"),
            fuel_gas_flow_km3h=payload.get("fuel_gas_flow_km3h"),
            steam_flow_tonh=payload.get("steam_flow_tonh"),
            feed_flow_tonh=payload.get("feed_flow_tonh"),
            reactor_temp_c=payload.get("reactor_temp_c"),
            pressure_bar=payload.get("pressure_bar"),
            energy_intensity_kgoe_ton=payload.get("energy_intensity_kgoe_ton"),
            carbon_emission_kgco2_ton=payload.get("carbon_emission_kgco2_ton"),
            energy_efficiency_percent=payload.get("energy_efficiency_percent"),
            source=payload.get("source"),
            quality=payload.get("quality"),
        )
        with self._lock:
            self._series[reading.plant_code].append(reading)
        return reading

    def latest(self, plant_code: str) -> MemoryReading | None:
        with self._lock:
            series = self._series.get(plant_code)
            if not series:
                return None
            return series[-1]

    def history(self, plant_code: str, *, minutes: int = 15) -> list[MemoryReading]:
        since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        with self._lock:
            series = list(self._series.get(plant_code, ()))
        return [r for r in series if r.time >= since]


memory_store = MemoryStore()
