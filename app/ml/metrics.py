"""Evaluation metrics for energy prediction (NFR-PER-02)."""

from __future__ import annotations

import numpy as np


def mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Mean Absolute Percentage Error in percent."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    denom = np.clip(np.abs(y_true), 1e-6, None)
    return float(np.mean(np.abs((y_true - y_pred) / denom)) * 100.0)


def multi_output_mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Average MAPE across output columns."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    if y_true.ndim == 1:
        return mape(y_true, y_pred)
    scores = [mape(y_true[:, i], y_pred[:, i]) for i in range(y_true.shape[1])]
    return float(np.mean(scores))
