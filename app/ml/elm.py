"""Extreme Learning Machine (FR-ML-02) — fast single-hidden-layer network."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -40, 40)))


@dataclass
class ELMModel:
    n_hidden: int
    input_dim: int
    output_dim: int
    W: np.ndarray
    b: np.ndarray
    beta: np.ndarray
    x_mean: np.ndarray
    x_std: np.ndarray
    y_mean: np.ndarray
    y_std: np.ndarray

    def predict(self, X: np.ndarray) -> np.ndarray:
        Xs = (X - self.x_mean) / self.x_std
        H = _sigmoid(Xs @ self.W + self.b)
        Ys = H @ self.beta
        return Ys * self.y_std + self.y_mean


def train_elm(
    X: np.ndarray,
    y: np.ndarray,
    *,
    n_hidden: int = 64,
    seed: int = 42,
) -> ELMModel:
    rng = np.random.default_rng(seed)
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    if y.ndim == 1:
        y = y.reshape(-1, 1)

    x_mean = X.mean(axis=0)
    x_std = X.std(axis=0)
    x_std[x_std < 1e-8] = 1.0
    y_mean = y.mean(axis=0)
    y_std = y.std(axis=0)
    y_std[y_std < 1e-8] = 1.0

    Xs = (X - x_mean) / x_std
    Ys = (y - y_mean) / y_std

    n_features = Xs.shape[1]
    W = rng.normal(0, 1, size=(n_features, n_hidden))
    b = rng.normal(0, 1, size=(n_hidden,))
    H = _sigmoid(Xs @ W + b)
    beta = np.linalg.pinv(H) @ Ys

    return ELMModel(
        n_hidden=n_hidden,
        input_dim=n_features,
        output_dim=y.shape[1],
        W=W,
        b=b,
        beta=beta,
        x_mean=x_mean,
        x_std=x_std,
        y_mean=y_mean,
        y_std=y_std,
    )
