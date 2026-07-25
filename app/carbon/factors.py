"""Load per-plant IPCC-style emission factors (FR-CAR-01)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.core.config import get_settings


@dataclass(frozen=True)
class EmissionFactors:
    plant_code: str
    natural_gas_kgco2_per_m3: float
    steam_kgco2_per_ton: float
    electricity_kgco2_per_kwh: float
    version: str
    source: str
    notes: str = ""


def _default_path() -> Path:
    settings = get_settings()
    path = Path(settings.carbon_factors_path)
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parents[2] / path


def load_emission_factors(path: Path | None = None) -> dict[str, EmissionFactors]:
    map_path = path or _default_path()
    with map_path.open(encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}

    version = str(raw.get("version", "unknown"))
    source = str(raw.get("source", ""))
    defaults = raw.get("defaults") or {}
    plants: dict[str, EmissionFactors] = {}

    for code, meta in (raw.get("plants") or {}).items():
        plants[code] = EmissionFactors(
            plant_code=code,
            natural_gas_kgco2_per_m3=float(
                meta.get("natural_gas_kgco2_per_m3", defaults.get("natural_gas_kgco2_per_m3", 2.0))
            ),
            steam_kgco2_per_ton=float(
                meta.get("steam_kgco2_per_ton", defaults.get("steam_kgco2_per_ton", 0.3))
            ),
            electricity_kgco2_per_kwh=float(
                meta.get(
                    "electricity_kgco2_per_kwh",
                    defaults.get("electricity_kgco2_per_kwh", 0.5),
                )
            ),
            version=version,
            source=source,
            notes=str(meta.get("notes", "")),
        )
    return plants


@lru_cache
def get_emission_factors() -> dict[str, EmissionFactors]:
    return load_emission_factors()


def factors_for(plant_code: str) -> EmissionFactors:
    factors = get_emission_factors()
    if plant_code in factors:
        return factors[plant_code]
    # Fallback to settings defaults
    settings = get_settings()
    return EmissionFactors(
        plant_code=plant_code,
        natural_gas_kgco2_per_m3=settings.ef_natural_gas_kgco2_per_m3,
        steam_kgco2_per_ton=settings.ef_steam_kgco2_per_ton,
        electricity_kgco2_per_kwh=settings.ef_electricity_kgco2_per_kwh,
        version="settings-fallback",
        source="app settings",
    )
