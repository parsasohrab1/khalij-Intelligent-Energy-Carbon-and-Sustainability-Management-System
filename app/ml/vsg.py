"""FR-ML-01 — VSG on real / empirical distributions (MC + PSO)."""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

from app.ml.features import FEATURE_COLUMNS
from app.services.physics import enrich_reading
from app.services.vsg import FEATURE_BOUNDS, generate_monte_carlo, generate_pso


def _empirical_stats(frame: pd.DataFrame) -> dict[str, tuple[float, float, float, float]]:
    """Return mean, std, lo, hi per feature from real samples."""
    stats: dict[str, tuple[float, float, float, float]] = {}
    for col in FEATURE_COLUMNS:
        series = frame[col].astype(float)
        mean = float(series.mean())
        std = float(series.std(ddof=0) or 1.0)
        lo = float(series.min())
        hi = float(series.max())
        # widen slightly for exploration
        pad = 0.05 * (hi - lo + 1e-6)
        stats[col] = (mean, max(std, 1e-3), lo - pad, hi + pad)
    return stats


def generate_monte_carlo_from_real(
    real_frame: pd.DataFrame,
    n_samples: int = 100,
    seed: int = 42,
) -> list[dict[str, float]]:
    """Sample around empirical means (Gaussian) clipped to observed bounds."""
    rng = np.random.default_rng(seed)
    stats = _empirical_stats(real_frame)
    samples: list[dict[str, float]] = []
    for _ in range(n_samples):
        base = {}
        for col in FEATURE_COLUMNS:
            mean, std, lo, hi = stats[col]
            value = float(rng.normal(mean, std))
            base[col] = float(np.clip(value, lo, hi))
        derived = enrich_reading(**base)
        samples.append({**{k: round(v, 2) for k, v in base.items()}, **derived})
    return samples


def generate_pso_from_real(
    real_frame: pd.DataFrame,
    n_samples: int = 100,
    seed: int = 42,
    n_particles: int = 30,
    n_iters: int = 40,
) -> list[dict[str, float]]:
    """PSO within empirical bounds, seeded from real rows."""
    rng = np.random.default_rng(seed)
    stats = _empirical_stats(real_frame)
    keys = list(FEATURE_COLUMNS)
    lows = np.array([stats[k][2] for k in keys])
    highs = np.array([stats[k][3] for k in keys])

    # seed particles from real data (+ noise)
    real_X = real_frame.loc[:, keys].to_numpy(dtype=float)
    take = min(len(real_X), n_particles)
    positions = np.zeros((n_particles, len(keys)))
    positions[:take] = real_X[rng.choice(len(real_X), size=take, replace=False)]
    if take < n_particles:
        positions[take:] = rng.uniform(lows, highs, size=(n_particles - take, len(keys)))
    positions += rng.normal(0, 0.01, size=positions.shape) * (highs - lows)
    positions = np.clip(positions, lows, highs)
    velocities = rng.normal(0, 0.2, size=positions.shape)
    personal_best = positions.copy()

    def fitness(row: np.ndarray) -> float:
        params = {k: float(row[i]) for i, k in enumerate(keys)}
        return enrich_reading(**params)["energy_intensity_kgoe_ton"]

    personal_scores = np.array([fitness(p) for p in personal_best])
    global_best = personal_best[int(np.argmin(personal_scores))].copy()
    archive: list[dict[str, float]] = []
    w, c1, c2 = 0.6, 1.4, 1.4

    for _ in range(n_iters):
        r1 = rng.random(positions.shape)
        r2 = rng.random(positions.shape)
        velocities = (
            w * velocities
            + c1 * r1 * (personal_best - positions)
            + c2 * r2 * (global_best - positions)
        )
        positions = np.clip(positions + velocities, lows, highs)
        for i, pos in enumerate(positions):
            score = fitness(pos)
            if score < personal_scores[i]:
                personal_scores[i] = score
                personal_best[i] = pos.copy()
            base = {k: float(pos[j]) for j, k in enumerate(keys)}
            derived = enrich_reading(**base)
            archive.append({**{k: round(v, 2) for k, v in base.items()}, **derived})
        global_best = personal_best[int(np.argmin(personal_scores))].copy()

    if len(archive) > n_samples:
        idx = rng.choice(len(archive), size=n_samples, replace=False)
        return [archive[i] for i in idx]
    return archive


def augment_with_vsg(
    real_frame: pd.DataFrame | None,
    *,
    method: str = "mc",
    n_samples: int = 200,
    seed: int = 42,
) -> list[dict[str, float]]:
    """
    Generate virtual samples.
    Prefer empirical distributions when real_frame is provided; else uniform bounds.
    """
    if real_frame is None or real_frame.empty:
        if method == "pso":
            return generate_pso(n_samples=n_samples, seed=seed)
        return generate_monte_carlo(n_samples=n_samples, seed=seed)
    if method == "pso":
        return generate_pso_from_real(real_frame, n_samples=n_samples, seed=seed)
    return generate_monte_carlo_from_real(real_frame, n_samples=n_samples, seed=seed)


def merge_real_and_virtual(
    real_frame: pd.DataFrame,
    virtual_samples: Sequence[dict[str, float]],
) -> pd.DataFrame:
    virtual_df = pd.DataFrame(list(virtual_samples))
    cols = list(FEATURE_COLUMNS) + ["energy_intensity_kgoe_ton", "carbon_emission_kgco2_ton"]
    real_part = real_frame.loc[:, [c for c in cols if c in real_frame.columns]].copy()
    virtual_part = virtual_df.loc[:, [c for c in cols if c in virtual_df.columns]].copy()
    return pd.concat([real_part, virtual_part], ignore_index=True)
