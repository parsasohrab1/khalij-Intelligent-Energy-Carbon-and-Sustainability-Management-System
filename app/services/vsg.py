"""FR-ML-01 — Virtual Sample Generation via Monte Carlo and PSO."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.services.physics import enrich_reading

FEATURE_BOUNDS: dict[str, tuple[float, float]] = {
    "electricity_power_mw": (5.0, 25.0),
    "fuel_gas_flow_km3h": (50.0, 150.0),
    "steam_flow_tonh": (10.0, 50.0),
    "feed_flow_tonh": (80.0, 120.0),
    "reactor_temp_c": (380.0, 420.0),
}


def _sample_uniform(rng: np.random.Generator, n: int) -> dict[str, np.ndarray]:
    return {
        name: rng.uniform(lo, hi, size=n)
        for name, (lo, hi) in FEATURE_BOUNDS.items()
    }


def generate_monte_carlo(n_samples: int = 100, seed: int = 42) -> list[dict[str, float]]:
    rng = np.random.default_rng(seed)
    raw = _sample_uniform(rng, n_samples)
    samples: list[dict[str, float]] = []
    for i in range(n_samples):
        base = {k: float(raw[k][i]) for k in FEATURE_BOUNDS}
        derived = enrich_reading(**base)
        samples.append({**{k: round(v, 2) for k, v in base.items()}, **derived})
    return samples


def generate_pso(
    n_samples: int = 100,
    seed: int = 42,
    n_particles: int = 30,
    n_iters: int = 40,
) -> list[dict[str, float]]:
    rng = np.random.default_rng(seed)
    keys = list(FEATURE_BOUNDS.keys())
    lows = np.array([FEATURE_BOUNDS[k][0] for k in keys])
    highs = np.array([FEATURE_BOUNDS[k][1] for k in keys])

    positions = rng.uniform(lows, highs, size=(n_particles, len(keys)))
    velocities = rng.normal(0, 0.5, size=positions.shape)
    personal_best = positions.copy()

    def fitness(row: np.ndarray) -> float:
        params = dict(zip(keys, row, strict=True))
        return enrich_reading(**params)["energy_intensity_kgoe_ton"]

    personal_scores = np.array([fitness(p) for p in personal_best])
    gbest_idx = int(np.argmin(personal_scores))
    global_best = personal_best[gbest_idx].copy()

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
        gbest_idx = int(np.argmin(personal_scores))
        global_best = personal_best[gbest_idx].copy()

    if len(archive) > n_samples:
        idx = rng.choice(len(archive), size=n_samples, replace=False)
        return [archive[i] for i in idx]
    return archive


def generate_virtual_samples(
    method: str = "mc",
    n_samples: int = 100,
    seed: int = 42,
    real_frame: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    """Prefer empirical VSG when real_frame is provided."""
    from app.ml.vsg import augment_with_vsg

    return augment_with_vsg(
        real_frame,
        method=method,
        n_samples=n_samples,
        seed=seed,
    )
