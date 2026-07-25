"""Build training datasets from TimescaleDB, CSV, or synthetic process data."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Plant, SensorReading
from app.ingestion.opcua_client import simulate_plant_reading
from app.ml.features import FEATURE_COLUMNS, TARGET_COLUMNS
from app.services.physics import enrich_reading

logger = logging.getLogger(__name__)


@dataclass
class MLDataset:
    frame: pd.DataFrame
    source: str
    plant_code: str

    @property
    def X(self) -> np.ndarray:
        return self.frame.loc[:, list(FEATURE_COLUMNS)].to_numpy(dtype=float)

    @property
    def y(self) -> np.ndarray:
        return self.frame.loc[:, list(TARGET_COLUMNS)].to_numpy(dtype=float)

    def __len__(self) -> int:
        return len(self.frame)


def _frame_from_records(records: list[dict[str, Any]], plant_code: str) -> pd.DataFrame:
    rows = []
    for rec in records:
        base = {c: float(rec[c]) for c in FEATURE_COLUMNS if c in rec}
        if len(base) < len(FEATURE_COLUMNS):
            continue
        if any(t not in rec for t in TARGET_COLUMNS):
            derived = enrich_reading(**base)
            base.update(derived)
        else:
            base.update({t: float(rec[t]) for t in TARGET_COLUMNS})
        rows.append(base)
    return pd.DataFrame(rows)


def build_synthetic_dataset(
    n_samples: int = 2000,
    plant_code: str = "olefin",
    seed: int = 42,
) -> MLDataset:
    rng = np.random.default_rng(seed)
    records = []
    for i in range(n_samples):
        sample = simulate_plant_reading(plant_code, elapsed_s=float(i) + float(rng.random()))
        # inject small noise so models generalize beyond exact physics
        for col in FEATURE_COLUMNS:
            sample[col] = float(sample[col]) * (1.0 + float(rng.normal(0, 0.005)))
        derived = enrich_reading(
            electricity_power_mw=sample["electricity_power_mw"],
            fuel_gas_flow_km3h=sample["fuel_gas_flow_km3h"],
            steam_flow_tonh=sample["steam_flow_tonh"],
            feed_flow_tonh=sample["feed_flow_tonh"],
            reactor_temp_c=sample["reactor_temp_c"],
        )
        sample.update(derived)
        records.append(sample)
    return MLDataset(frame=_frame_from_records(records, plant_code), source="synthetic", plant_code=plant_code)


def load_csv_dataset(path: str | Path, plant_code: str = "olefin") -> MLDataset:
    df = pd.read_csv(path)
    rename = {}
    if "timestamp" in df.columns and "time" not in df.columns:
        rename["timestamp"] = "time"
    df = df.rename(columns=rename)
    records = df.to_dict(orient="records")
    return MLDataset(frame=_frame_from_records(records, plant_code), source=str(path), plant_code=plant_code)


async def load_db_dataset(
    session: AsyncSession,
    plant_code: str,
    *,
    limit: int = 5000,
    lookback_hours: int = 24,
) -> MLDataset | None:
    since = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    result = await session.execute(
        select(SensorReading)
        .join(Plant, Plant.id == SensorReading.plant_id)
        .where(Plant.code == plant_code, SensorReading.time >= since)
        .order_by(SensorReading.time.desc())
        .limit(limit)
    )
    rows = list(result.scalars().all())
    if not rows:
        return None
    records = [
        {
            "electricity_power_mw": r.electricity_power_mw,
            "fuel_gas_flow_km3h": r.fuel_gas_flow_km3h,
            "steam_flow_tonh": r.steam_flow_tonh,
            "feed_flow_tonh": r.feed_flow_tonh,
            "reactor_temp_c": r.reactor_temp_c,
            "energy_intensity_kgoe_ton": r.energy_intensity_kgoe_ton,
            "carbon_emission_kgco2_ton": r.carbon_emission_kgco2_ton,
        }
        for r in reversed(rows)
    ]
    frame = _frame_from_records(records, plant_code)
    if frame.empty:
        return None
    return MLDataset(frame=frame, source="timescaledb", plant_code=plant_code)


def train_test_split(
    dataset: MLDataset,
    *,
    test_ratio: float = 0.2,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    n = len(dataset)
    idx = np.arange(n)
    rng.shuffle(idx)
    cut = max(1, int(n * (1 - test_ratio)))
    train_idx, test_idx = idx[:cut], idx[cut:]
    if len(test_idx) == 0:
        test_idx = train_idx[-max(1, n // 5) :]
    X, y = dataset.X, dataset.y
    return X[train_idx], y[train_idx], X[test_idx], y[test_idx]
