"""OPC-UA reader with process simulator fallback (R-GEN-01, FR-DATA-01/02)."""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings, get_settings
from app.ingestion.tag_map import SENSOR_FIELDS, get_tag_map
from app.services.physics import enrich_reading

logger = logging.getLogger(__name__)

# Nominal baselines per plant for the 1 Hz simulator
_SIM_BASE: dict[str, dict[str, float]] = {
    "olefin": {
        "electricity_power_mw": 15.0,
        "fuel_gas_flow_km3h": 100.0,
        "steam_flow_tonh": 30.0,
        "feed_flow_tonh": 100.0,
        "reactor_temp_c": 400.0,
        "pressure_bar": 12.5,
    },
    "pta": {
        "electricity_power_mw": 18.0,
        "fuel_gas_flow_km3h": 110.0,
        "steam_flow_tonh": 35.0,
        "feed_flow_tonh": 95.0,
        "reactor_temp_c": 405.0,
        "pressure_bar": 11.8,
    },
}


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def simulate_plant_reading(plant_code: str, elapsed_s: float | None = None) -> dict[str, Any]:
    """Generate one realistic 1 Hz sample for a plant (sine + noise-free drift)."""
    t = elapsed_s if elapsed_s is not None else time.time()
    base = _SIM_BASE.get(plant_code, _SIM_BASE["olefin"])
    phase = 0.0 if plant_code == "olefin" else 1.2

    raw = {
        "electricity_power_mw": _clip(
            base["electricity_power_mw"] + 5 * math.sin(0.2 * t + phase), 5, 25
        ),
        "fuel_gas_flow_km3h": _clip(
            base["fuel_gas_flow_km3h"] + 30 * math.sin(0.15 * t + 1.5 + phase), 50, 150
        ),
        "steam_flow_tonh": _clip(
            base["steam_flow_tonh"] + 10 * math.sin(0.25 * t + 0.8 + phase), 10, 50
        ),
        "feed_flow_tonh": _clip(
            base["feed_flow_tonh"] + 15 * math.sin(0.1 * t + 2.0 + phase), 80, 120
        ),
        "reactor_temp_c": _clip(
            base["reactor_temp_c"] + 15 * math.sin(0.2 * t + 1.0 + phase), 380, 420
        ),
        "pressure_bar": _clip(
            base["pressure_bar"] + 0.8 * math.sin(0.12 * t + phase), 8, 18
        ),
    }
    derived = enrich_reading(
        electricity_power_mw=raw["electricity_power_mw"],
        fuel_gas_flow_km3h=raw["fuel_gas_flow_km3h"],
        steam_flow_tonh=raw["steam_flow_tonh"],
        feed_flow_tonh=raw["feed_flow_tonh"],
        reactor_temp_c=raw["reactor_temp_c"],
    )
    now = datetime.now(timezone.utc)
    return {
        "time": now.isoformat(),
        "plant_code": plant_code,
        "source": "simulator",
        **{k: round(v, 3) for k, v in raw.items()},
        **derived,
    }


async def read_opcua_plant(
    plant_code: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """
    Read mapped OPC-UA tags for a plant.
    Falls back to simulator when endpoint is empty or source=simulator.
    """
    cfg = settings or get_settings()
    tag_map = get_tag_map()
    if plant_code not in tag_map:
        raise KeyError(f"Unknown plant_code '{plant_code}' in tag map")

    if cfg.ingestion_source == "simulator" or not cfg.opc_ua_endpoint:
        return simulate_plant_reading(plant_code)

    try:
        from asyncua import Client
    except ImportError as exc:
        raise RuntimeError(
            "OPC-UA mode requires asyncua. Install with: pip install 'iems[opcua]'"
        ) from exc

    plant = tag_map[plant_code]
    values: dict[str, float] = {}
    async with Client(url=cfg.opc_ua_endpoint) as client:
        for field in SENSOR_FIELDS:
            tag = plant.tags.get(field)
            if tag is None:
                continue
            node = client.get_node(tag.node_id)
            values[field] = float(await node.read_value())

    missing = [f for f in SENSOR_FIELDS if f not in values]
    if missing:
        raise RuntimeError(f"OPC-UA missing tags for {plant_code}: {missing}")

    derived = enrich_reading(
        electricity_power_mw=values["electricity_power_mw"],
        fuel_gas_flow_km3h=values["fuel_gas_flow_km3h"],
        steam_flow_tonh=values["steam_flow_tonh"],
        feed_flow_tonh=values["feed_flow_tonh"],
        reactor_temp_c=values["reactor_temp_c"],
    )
    return {
        "time": datetime.now(timezone.utc).isoformat(),
        "plant_code": plant_code,
        "source": "opcua",
        **{k: round(v, 3) for k, v in values.items()},
        **derived,
    }
