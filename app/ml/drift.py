"""E8 — Population Stability Index (PSI) drift monitoring."""

from __future__ import annotations

from typing import Any

import numpy as np

from app.ml.features import FEATURE_COLUMNS


def compute_psi(reference: np.ndarray, current: np.ndarray, *, n_bins: int = 10) -> float:
    """PSI between two 1-D distributions (higher = more drift)."""
    ref = np.asarray(reference, dtype=float).ravel()
    cur = np.asarray(current, dtype=float).ravel()
    if ref.size < 5 or cur.size < 5:
        return 0.0
    lo = float(min(ref.min(), cur.min()))
    hi = float(max(ref.max(), cur.max()))
    if hi - lo < 1e-12:
        return 0.0
    bins = np.linspace(lo, hi, n_bins + 1)
    ref_hist, _ = np.histogram(ref, bins=bins)
    cur_hist, _ = np.histogram(cur, bins=bins)
    ref_p = ref_hist.astype(float) / max(ref_hist.sum(), 1)
    cur_p = cur_hist.astype(float) / max(cur_hist.sum(), 1)
    # avoid zeros
    ref_p = np.clip(ref_p, 1e-4, None)
    cur_p = np.clip(cur_p, 1e-4, None)
    ref_p = ref_p / ref_p.sum()
    cur_p = cur_p / cur_p.sum()
    return float(np.sum((cur_p - ref_p) * np.log(cur_p / ref_p)))


def feature_reference_stats(X: np.ndarray) -> dict[str, Any]:
    X = np.asarray(X, dtype=float)
    stats: dict[str, Any] = {"n": int(X.shape[0]), "features": {}}
    for i, name in enumerate(FEATURE_COLUMNS):
        col = X[:, i] if X.ndim == 2 and X.shape[1] > i else X.ravel()
        stats["features"][name] = {
            "mean": float(np.mean(col)),
            "std": float(np.std(col) + 1e-12),
            "min": float(np.min(col)),
            "max": float(np.max(col)),
            "hist": np.histogram(col, bins=10)[0].astype(int).tolist(),
            "edges": np.histogram(col, bins=10)[1].astype(float).tolist(),
        }
    return stats


def drift_report(
    reference_X: np.ndarray,
    current_X: np.ndarray,
    *,
    threshold: float = 0.2,
) -> dict[str, Any]:
    ref = np.asarray(reference_X, dtype=float)
    cur = np.asarray(current_X, dtype=float)
    per_feature: dict[str, float] = {}
    for i, name in enumerate(FEATURE_COLUMNS):
        if ref.ndim != 2 or cur.ndim != 2 or ref.shape[1] <= i or cur.shape[1] <= i:
            continue
        per_feature[name] = round(compute_psi(ref[:, i], cur[:, i]), 4)
    max_psi = max(per_feature.values()) if per_feature else 0.0
    return {
        "per_feature_psi": per_feature,
        "max_psi": round(max_psi, 4),
        "threshold": threshold,
        "drift_alert": bool(max_psi >= threshold),
    }
