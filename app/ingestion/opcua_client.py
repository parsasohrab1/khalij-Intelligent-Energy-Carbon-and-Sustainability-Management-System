"""OPC-UA reader with process simulator fallback (R-GEN-01, FR-DATA-01/02, E6)."""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings, get_settings
from app.ingestion.quality import (
    QualityCode,
    apply_scale,
    reading_quality_payload,
)
from app.ingestion.tag_map import SENSOR_FIELDS, get_tag_map
from app.services.physics import enrich_reading

logger = logging.getLogger(__name__)

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
    per_tag = {f: QualityCode.GOOD for f in SENSOR_FIELDS}
    q = reading_quality_payload(per_tag, allow_uncertain=True)
    return {
        "time": now.isoformat(),
        "plant_code": plant_code,
        "source": "simulator",
        **{k: round(v, 3) for k, v in raw.items()},
        **derived,
        **q,
    }


async def read_opcua_plant(
    plant_code: str,
    settings: Settings | None = None,
    *,
    use_session: bool = True,
) -> dict[str, Any]:
    """
    Read mapped OPC-UA tags for a plant with quality codes.
    Falls back to simulator unless plant_connect is enabled.
    """
    cfg = settings or get_settings()
    tag_map = get_tag_map()
    if plant_code not in tag_map:
        raise KeyError(f"Unknown plant_code '{plant_code}' in tag map")

    plant_mode = cfg.plant_connect or cfg.ingestion_source == "opcua"
    if not plant_mode or not cfg.opc_ua_endpoint:
        if cfg.plant_connect and not cfg.opc_ua_endpoint:
            raise RuntimeError(
                "PLANT_CONNECT=true requires OPC_UA_ENDPOINT (simulator fallback disabled)"
            )
        return simulate_plant_reading(plant_code)

    plant = tag_map[plant_code]
    values: dict[str, float] = {}
    per_tag: dict[str, QualityCode] = {}
    server_times: list[datetime] = []

    if use_session:
        from app.ingestion.opcua_session import get_plant_session

        session = get_plant_session(cfg)
        samples = await session.read_plant(plant)
        for field in SENSOR_FIELDS:
            tag = plant.tags.get(field)
            if tag is None:
                continue
            sample = samples.get(field)
            if sample is None:
                per_tag[field] = QualityCode.BAD
                continue
            per_tag[field] = sample.quality
            if sample.value is None:
                continue
            values[field] = apply_scale(sample.value, scale=tag.scale, offset=tag.offset)
            if sample.server_timestamp is not None:
                server_times.append(sample.server_timestamp)
    else:
        # One-shot poll (tests / diagnostics)
        try:
            from asyncua import Client
        except ImportError as exc:
            raise RuntimeError(
                "OPC-UA mode requires asyncua. Install with: pip install 'iems[opcua]'"
            ) from exc

        client = Client(url=cfg.opc_ua_endpoint)
        if cfg.opc_ua_username:
            client.set_user(cfg.opc_ua_username)
            client.set_password(cfg.opc_ua_password or "")
        async with client:
            for field in SENSOR_FIELDS:
                tag = plant.tags.get(field)
                if tag is None:
                    continue
                node = client.get_node(tag.node_id)
                try:
                    dv = await node.read_data_value()
                    from app.ingestion.quality import status_code_to_quality

                    status = int(dv.StatusCode.value) if dv.StatusCode is not None else None
                    quality = status_code_to_quality(status)
                    raw_val = float(dv.Value.Value)
                    values[field] = apply_scale(raw_val, scale=tag.scale, offset=tag.offset)
                    per_tag[field] = quality
                except Exception:  # noqa: BLE001
                    logger.exception("OPC one-shot read failed for %s.%s", plant_code, field)
                    per_tag[field] = QualityCode.BAD

    missing = [f for f in SENSOR_FIELDS if f not in values]
    if missing and cfg.plant_connect:
        # Still emit partial reading with Bad quality so alerts can fire
        logger.warning("OPC-UA incomplete tags for %s: %s", plant_code, missing)
        for f in missing:
            per_tag.setdefault(f, QualityCode.BAD)
    elif missing:
        raise RuntimeError(f"OPC-UA missing tags for {plant_code}: {missing}")

    # Fill missing numeric fields with None-safe zeros only when not plant_connect fail-hard
    for f in SENSOR_FIELDS:
        if f not in values:
            values[f] = float("nan")

    # Replace NaN with None for JSON / DB
    clean = {k: (None if isinstance(v, float) and math.isnan(v) else round(v, 3)) for k, v in values.items()}

    # Derived KPIs need complete numbers — skip if incomplete
    derived: dict[str, Any] = {}
    if all(clean.get(f) is not None for f in (
        "electricity_power_mw", "fuel_gas_flow_km3h", "steam_flow_tonh",
        "feed_flow_tonh", "reactor_temp_c",
    )):
        derived = enrich_reading(
            electricity_power_mw=float(clean["electricity_power_mw"]),
            fuel_gas_flow_km3h=float(clean["fuel_gas_flow_km3h"]),
            steam_flow_tonh=float(clean["steam_flow_tonh"]),
            feed_flow_tonh=float(clean["feed_flow_tonh"]),
            reactor_temp_c=float(clean["reactor_temp_c"]),
        )

    q = reading_quality_payload(per_tag, allow_uncertain=cfg.opc_ua_allow_uncertain)
    as_of = max(server_times) if server_times else datetime.now(timezone.utc)
    return {
        "time": as_of.isoformat(),
        "plant_code": plant_code,
        "source": "opcua",
        **clean,
        **derived,
        **q,
    }
