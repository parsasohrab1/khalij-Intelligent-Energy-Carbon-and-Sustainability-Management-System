"""E10 — light Scope 3 factors and calculation."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class Scope3Factors:
    plant_code: str
    cat3_fuel_upstream_kgco2_per_m3: float
    cat1_purchased_goods_kgco2_per_ton: float
    cat5_waste_kgco2_per_ton: float
    version: str
    source: str
    notes: str = ""


@dataclass
class Scope3Breakdown:
    cat3_fuel_upstream_kgco2: float
    cat1_purchased_goods_kgco2: float
    cat5_waste_kgco2: float
    total_kgco2: float
    factors_version: str
    detail: dict[str, float]


def _default_path(settings: Settings | None = None) -> Path:
    cfg = settings or get_settings()
    path = Path(cfg.carbon_scope3_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    return path


def load_scope3_factors(path: Path | None = None) -> dict[str, Scope3Factors]:
    map_path = path or _default_path()
    if not map_path.exists():
        return {}
    raw: dict[str, Any] = yaml.safe_load(map_path.read_text(encoding="utf-8")) or {}
    version = str(raw.get("version", "unknown"))
    source = str(raw.get("source", ""))
    defaults = raw.get("defaults") or {}
    out: dict[str, Scope3Factors] = {}
    for code, meta in (raw.get("plants") or {}).items():
        merged = {**defaults, **(meta or {})}
        out[code] = Scope3Factors(
            plant_code=code,
            cat3_fuel_upstream_kgco2_per_m3=float(
                merged.get("cat3_fuel_upstream_kgco2_per_m3", 0.35)
            ),
            cat1_purchased_goods_kgco2_per_ton=float(
                merged.get("cat1_purchased_goods_kgco2_per_ton", 12.0)
            ),
            cat5_waste_kgco2_per_ton=float(merged.get("cat5_waste_kgco2_per_ton", 1.5)),
            version=version,
            source=source,
            notes=str(merged.get("notes", "")),
        )
    return out


@lru_cache
def get_scope3_factors() -> dict[str, Scope3Factors]:
    return load_scope3_factors()


def reload_scope3_factors() -> dict[str, Scope3Factors]:
    get_scope3_factors.cache_clear()
    return get_scope3_factors()


def scope3_for(plant_code: str) -> Scope3Factors:
    factors = get_scope3_factors()
    if plant_code in factors:
        return factors[plant_code]
    # synthetic default
    return Scope3Factors(
        plant_code=plant_code,
        cat3_fuel_upstream_kgco2_per_m3=0.35,
        cat1_purchased_goods_kgco2_per_ton=12.0,
        cat5_waste_kgco2_per_ton=1.5,
        version="scope3-default",
        source="built-in",
    )


def compute_scope3(
    *,
    plant_code: str,
    fuel_gas_km3: float,
    product_ton: float,
) -> Scope3Breakdown:
    f = scope3_for(plant_code)
    # fuel_gas_km3 is thousand m³ → m³ = * 1000
    fuel_m3 = float(fuel_gas_km3) * 1000.0
    cat3 = fuel_m3 * f.cat3_fuel_upstream_kgco2_per_m3
    cat1 = float(product_ton) * f.cat1_purchased_goods_kgco2_per_ton
    cat5 = float(product_ton) * f.cat5_waste_kgco2_per_ton
    total = cat3 + cat1 + cat5
    return Scope3Breakdown(
        cat3_fuel_upstream_kgco2=round(cat3, 2),
        cat1_purchased_goods_kgco2=round(cat1, 2),
        cat5_waste_kgco2=round(cat5, 2),
        total_kgco2=round(total, 2),
        factors_version=f.version,
        detail={
            "fuel_gas_km3": float(fuel_gas_km3),
            "product_ton": float(product_ton),
            "cat3_factor": f.cat3_fuel_upstream_kgco2_per_m3,
            "cat1_factor": f.cat1_purchased_goods_kgco2_per_ton,
            "cat5_factor": f.cat5_waste_kgco2_per_ton,
        },
    )
