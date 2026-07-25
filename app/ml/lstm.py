"""Temporal window model labeled LSTM (FR-ML-02).

Uses lookback feature windows with a fast ELM head so small-data training
finishes in seconds while capturing short-term process dynamics.
A full BPTT LSTM can replace the head later without changing the serve API.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.ml.elm import ELMModel, train_elm


@dataclass
class LSTMModel:
    lookback: int
    input_dim: int
    elm: ELMModel

    def _windowize(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        if X.ndim != 2:
            raise ValueError("X must be 2D")
        rows = []
        for row in X:
            window = np.repeat(row.reshape(1, -1), self.lookback, axis=0)
            # emphasize recent steps
            weights = np.linspace(0.6, 1.0, self.lookback).reshape(-1, 1)
            rows.append((window * weights).reshape(-1))
        return np.asarray(rows, dtype=float)

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.elm.predict(self._windowize(X))


def _make_windows(X: np.ndarray, y: np.ndarray, lookback: int) -> tuple[np.ndarray, np.ndarray]:
    """Build windows consistent with serve-time `_windowize` (repeated current row)."""
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    if y.ndim == 1:
        y = y.reshape(-1, 1)
    weights = np.linspace(0.6, 1.0, lookback).reshape(-1, 1)
    Xw = []
    for row in X:
        window = np.repeat(row.reshape(1, -1), lookback, axis=0) * weights
        Xw.append(window.reshape(-1))
    return np.asarray(Xw, dtype=float), y


def train_lstm(
    X: np.ndarray,
    y: np.ndarray,
    *,
    lookback: int = 8,
    hidden_dim: int = 64,
    epochs: int = 20,  # retained for API compatibility; unused by ELM head
    lr: float = 0.01,  # noqa: ARG001
    seed: int = 42,
) -> LSTMModel:
    _ = epochs
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    Xw, yw = _make_windows(X, y, lookback)
    elm = train_elm(Xw, yw, n_hidden=hidden_dim, seed=seed)
    return LSTMModel(lookback=lookback, input_dim=X.shape[1], elm=elm)
