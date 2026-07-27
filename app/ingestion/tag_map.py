"""Load OPC-UA / simulator tag maps (FR-DATA-01, E6 Plant Connect)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.core.config import get_settings

SENSOR_FIELDS = (
    "electricity_power_mw",
    "fuel_gas_flow_km3h",
    "steam_flow_tonh",
    "feed_flow_tonh",
    "reactor_temp_c",
    "pressure_bar",
)


@dataclass(frozen=True)
class TagDef:
    field: str
    node_id: str
    unit: str
    description: str
    scale: float = 1.0
    offset: float = 0.0
    writable: bool = False
    write_node_id: str | None = None


@dataclass(frozen=True)
class PlantTagMap:
    code: str
    name: str
    tags: dict[str, TagDef]
    endpoint: str | None = None


def _default_path() -> Path:
    settings = get_settings()
    path = Path(settings.opc_ua_tag_map_path)
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parents[2] / path


def load_tag_map(path: Path | None = None) -> dict[str, PlantTagMap]:
    map_path = path or _default_path()
    with map_path.open(encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}

    plants: dict[str, PlantTagMap] = {}
    for code, plant in (raw.get("plants") or {}).items():
        tags: dict[str, TagDef] = {}
        for field, meta in (plant.get("tags") or {}).items():
            tags[field] = TagDef(
                field=field,
                node_id=str(meta["node_id"]),
                unit=str(meta.get("unit", "")),
                description=str(meta.get("description", "")),
                scale=float(meta.get("scale", 1.0)),
                offset=float(meta.get("offset", 0.0)),
                writable=bool(meta.get("writable", False)),
                write_node_id=(
                    str(meta["write_node_id"]) if meta.get("write_node_id") else None
                ),
            )
        endpoint = plant.get("endpoint")
        plants[code] = PlantTagMap(
            code=code,
            name=str(plant.get("name", code)),
            tags=tags,
            endpoint=str(endpoint) if endpoint else None,
        )
    return plants


@lru_cache
def get_tag_map() -> dict[str, PlantTagMap]:
    return load_tag_map()


def reload_tag_map() -> dict[str, PlantTagMap]:
    get_tag_map.cache_clear()
    return get_tag_map()


def list_tag_map() -> dict[str, Any]:
    """API-friendly dump of the configured tag map."""
    plants = get_tag_map()
    out: dict[str, Any] = {}
    for code, plant in plants.items():
        out[code] = {
            "name": plant.name,
            "endpoint": plant.endpoint,
            "tags": {
                field: {
                    "node_id": tag.node_id,
                    "unit": tag.unit,
                    "description": tag.description,
                    "scale": tag.scale,
                    "offset": tag.offset,
                    "writable": tag.writable,
                    "write_node_id": tag.write_node_id,
                }
                for field, tag in plant.tags.items()
            },
        }
    return out
