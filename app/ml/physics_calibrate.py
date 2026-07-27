"""E8 — plant physics calibration (affine scales on SRS formulas)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from app.core.config import Settings, get_settings
from app.ml.features import FEATURE_COLUMNS, TARGET_COLUMNS
from app.services import physics as physics_mod

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PhysicsCalibration:
    plant_code: str
    energy_scale: float = 1.0
    energy_offset: float = 0.0
    carbon_scale: float = 1.0
    carbon_offset: float = 0.0
    version: str = "default"


def _default_path(settings: Settings | None = None) -> Path:
    cfg = settings or get_settings()
    path = Path(cfg.ml_physics_scale_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    return path


def load_calibration(
    plant_code: str,
    settings: Settings | None = None,
) -> PhysicsCalibration:
    path = _default_path(settings)
    if not path.exists():
        return PhysicsCalibration(plant_code=plant_code)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    plants = raw.get("plants") or {}
    meta = plants.get(plant_code) or {}
    return PhysicsCalibration(
        plant_code=plant_code,
        energy_scale=float(meta.get("energy_scale", 1.0)),
        energy_offset=float(meta.get("energy_offset", 0.0)),
        carbon_scale=float(meta.get("carbon_scale", 1.0)),
        carbon_offset=float(meta.get("carbon_offset", 0.0)),
        version=str(meta.get("version", raw.get("version", "default"))),
    )


@lru_cache
def get_calibration(plant_code: str) -> PhysicsCalibration:
    return load_calibration(plant_code)


def reload_calibration() -> None:
    get_calibration.cache_clear()


def calibrated_enrich(
    *,
    plant_code: str,
    electricity_power_mw: float,
    fuel_gas_flow_km3h: float,
    steam_flow_tonh: float,
    feed_flow_tonh: float,
    reactor_temp_c: float,
    settings: Settings | None = None,
) -> dict[str, float]:
    cal = load_calibration(plant_code, settings)
    base = physics_mod.enrich_reading(
        electricity_power_mw=electricity_power_mw,
        fuel_gas_flow_km3h=fuel_gas_flow_km3h,
        steam_flow_tonh=steam_flow_tonh,
        feed_flow_tonh=feed_flow_tonh,
        reactor_temp_c=reactor_temp_c,
    )
    ei = base["energy_intensity_kgoe_ton"] * cal.energy_scale + cal.energy_offset
    ce = base["carbon_emission_kgco2_ton"] * cal.carbon_scale + cal.carbon_offset
    return {
        "energy_intensity_kgoe_ton": round(float(ei), 2),
        "carbon_emission_kgco2_ton": round(float(ce), 2),
        "energy_efficiency_percent": round(physics_mod.energy_efficiency(float(ei)), 2),
        "physics_cal_version": cal.version,
    }


def fit_calibration_from_xy(
    X: np.ndarray,
    y: np.ndarray,
    plant_code: str,
) -> PhysicsCalibration:
    """Least-squares affine fit: scale*physics(X)+offset ≈ y_plant."""
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    if y.ndim == 1:
        y = y.reshape(-1, 1)
    phys_ei = []
    phys_ce = []
    for row in X:
        feats = {FEATURE_COLUMNS[i]: float(row[i]) for i in range(len(FEATURE_COLUMNS))}
        ei = physics_mod.energy_intensity(
            feats["fuel_gas_flow_km3h"],
            feats["steam_flow_tonh"],
            feats["feed_flow_tonh"],
            feats["reactor_temp_c"],
        )
        ce = physics_mod.carbon_emission_intensity(
            feats["fuel_gas_flow_km3h"],
            feats["steam_flow_tonh"],
            feats["electricity_power_mw"],
        )
        phys_ei.append(ei)
        phys_ce.append(ce)
    phys_ei = np.asarray(phys_ei)
    phys_ce = np.asarray(phys_ce)
    y_ei = y[:, 0]
    y_ce = y[:, 1] if y.shape[1] > 1 else y[:, 0]

    def _affine(xp: np.ndarray, yp: np.ndarray) -> tuple[float, float]:
        A = np.column_stack([xp, np.ones_like(xp)])
        coef, _, _, _ = np.linalg.lstsq(A, yp, rcond=None)
        return float(coef[0]), float(coef[1])

    es, eo = _affine(phys_ei, y_ei)
    cs, co = _affine(phys_ce, y_ce)
    return PhysicsCalibration(
        plant_code=plant_code,
        energy_scale=es,
        energy_offset=eo,
        carbon_scale=cs,
        carbon_offset=co,
        version="fitted",
    )


def save_calibration(
    cal: PhysicsCalibration,
    settings: Settings | None = None,
) -> Path:
    path = _default_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw: dict[str, Any] = {}
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    plants = dict(raw.get("plants") or {})
    plants[cal.plant_code] = {
        "energy_scale": cal.energy_scale,
        "energy_offset": cal.energy_offset,
        "carbon_scale": cal.carbon_scale,
        "carbon_offset": cal.carbon_offset,
        "version": cal.version,
    }
    payload = {"version": cal.version, "plants": plants}
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    reload_calibration()
    logger.info("Saved physics calibration for %s → %s", cal.plant_code, path)
    return path
