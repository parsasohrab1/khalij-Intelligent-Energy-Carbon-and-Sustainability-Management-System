"""Temporal sequence model for FR-ML-02 (E8 Trusted Models).

Prefer a real PyTorch LSTM when `torch` is installed (`iems[ml]`).
Otherwise train an ELM head on **true consecutive lookback windows**
(not repeated current-row stubs).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.ml.elm import ELMModel, train_elm

logger = logging.getLogger(__name__)


def build_temporal_windows(
    X: np.ndarray,
    y: np.ndarray,
    lookback: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Sliding windows over consecutive samples.
    Returns (X_seq [n, lookback, f], y_out [n, t], X_flat [n, lookback*f]).
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    if y.ndim == 1:
        y = y.reshape(-1, 1)
    if len(X) < lookback:
        # pad by repeating first row so demos still train
        pad = np.repeat(X[:1], lookback - len(X), axis=0)
        X = np.vstack([pad, X])
        y = np.vstack([np.repeat(y[:1], lookback - len(y), axis=0), y]) if len(y) < lookback else y
    seqs = []
    flats = []
    outs = []
    for i in range(lookback - 1, len(X)):
        window = X[i - lookback + 1 : i + 1]
        seqs.append(window)
        flats.append(window.reshape(-1))
        outs.append(y[i])
    return (
        np.asarray(seqs, dtype=float),
        np.asarray(outs, dtype=float),
        np.asarray(flats, dtype=float),
    )


@dataclass
class LSTMModel:
    """Serializable model wrapper used by registry/serve."""

    lookback: int
    input_dim: int
    backend: str  # torch | temporal_elm
    elm: ELMModel | None = None
    torch_state: dict[str, Any] | None = None
    hidden_dim: int = 16
    output_dim: int = 2

    def predict(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        if self.backend == "torch" and self.torch_state is not None:
            return _torch_predict(self, X)
        assert self.elm is not None
        flat = _to_flat_windows(X, self.lookback)
        return self.elm.predict(flat)


def _to_flat_windows(X: np.ndarray, lookback: int) -> np.ndarray:
    X = np.asarray(X, dtype=float)
    if X.ndim == 3:
        return X.reshape(X.shape[0], -1)
    if X.ndim != 2:
        raise ValueError("X must be 2D or 3D")
    if X.shape[0] >= lookback:
        # treat rows as a contiguous series → last window(s)
        _, _, flat = build_temporal_windows(X, np.zeros((len(X), 1)), lookback)
        return flat
    # single-row / short batch: repeat (demo only)
    rows = []
    weights = np.linspace(0.6, 1.0, lookback).reshape(-1, 1)
    for row in X:
        window = np.repeat(row.reshape(1, -1), lookback, axis=0) * weights
        rows.append(window.reshape(-1))
    return np.asarray(rows, dtype=float)


def _try_train_torch(
    X_seq: np.ndarray,
    y: np.ndarray,
    *,
    hidden_dim: int,
    epochs: int,
    lr: float,
    seed: int,
) -> dict[str, Any] | None:
    try:
        import torch
        from torch import nn
    except ImportError:
        return None

    try:
        torch.manual_seed(seed)
        device = torch.device("cpu")
        n, lookback, feat = X_seq.shape
        out_dim = y.shape[1]

        class _Net(nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.lstm = nn.LSTM(feat, hidden_dim, batch_first=True)
                self.head = nn.Linear(hidden_dim, out_dim)

            def forward(self, x: torch.Tensor) -> torch.Tensor:
                out, _ = self.lstm(x)
                return self.head(out[:, -1, :])

        model = _Net().to(device)
        # SGD avoids some torch.optim.Adam import side-effects (onnxruntime) on Windows
        opt = torch.optim.SGD(model.parameters(), lr=lr)
        loss_fn = nn.MSELoss()
        xt = torch.tensor(X_seq, dtype=torch.float32, device=device)
        yt = torch.tensor(y, dtype=torch.float32, device=device)
        model.train()
        for _ in range(max(1, epochs)):
            opt.zero_grad()
            pred = model(xt)
            loss = loss_fn(pred, yt)
            loss.backward()
            opt.step()
        model.eval()
        state = {
            "state_dict": {k: v.detach().cpu().numpy() for k, v in model.state_dict().items()},
            "hidden_dim": hidden_dim,
            "input_dim": feat,
            "output_dim": out_dim,
            "lookback": lookback,
        }
        logger.info("Trained torch LSTM epochs=%s hidden=%s", epochs, hidden_dim)
        return state
    except Exception:
        logger.exception("Torch LSTM training failed; falling back to temporal-ELM")
        return None


def _torch_predict(model: LSTMModel, X: np.ndarray) -> np.ndarray:
    import torch
    from torch import nn

    st = model.torch_state or {}
    feat = int(st["input_dim"])
    hidden = int(st["hidden_dim"])
    out_dim = int(st["output_dim"])
    lookback = int(st["lookback"])

    class _Net(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.lstm = nn.LSTM(feat, hidden, batch_first=True)
            self.head = nn.Linear(hidden, out_dim)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            out, _ = self.lstm(x)
            return self.head(out[:, -1, :])

    net = _Net()
    sd = {k: torch.tensor(v) for k, v in st["state_dict"].items()}
    net.load_state_dict(sd)
    net.eval()

    if X.ndim == 2:
        if X.shape[0] >= lookback:
            X_seq, _, _ = build_temporal_windows(X, np.zeros((len(X), out_dim)), lookback)
        else:
            X_seq = np.stack([np.repeat(X[-1:].reshape(1, -1), lookback, axis=0)], axis=0)
    else:
        X_seq = X
    with torch.no_grad():
        pred = net(torch.tensor(X_seq, dtype=torch.float32)).numpy()
    return pred


def train_lstm(
    X: np.ndarray,
    y: np.ndarray,
    *,
    lookback: int = 8,
    hidden_dim: int = 16,
    epochs: int = 20,
    lr: float = 0.01,
    seed: int = 42,
    prefer_torch: bool = True,
) -> LSTMModel:
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    if y.ndim == 1:
        y = y.reshape(-1, 1)

    X_seq, y_out, X_flat = build_temporal_windows(X, y, lookback)
    backend = "temporal_elm"
    torch_state = None
    elm = None

    if prefer_torch:
        torch_state = _try_train_torch(
            X_seq, y_out, hidden_dim=hidden_dim, epochs=epochs, lr=lr, seed=seed
        )
        if torch_state is not None:
            backend = "torch"

    if backend == "temporal_elm":
        elm = train_elm(X_flat, y_out, n_hidden=max(hidden_dim, 32), seed=seed)
        logger.info("Trained temporal-ELM LSTM lookback=%s windows=%s", lookback, len(X_flat))

    return LSTMModel(
        lookback=lookback,
        input_dim=X.shape[1],
        backend=backend,
        elm=elm,
        torch_state=torch_state,
        hidden_dim=hidden_dim,
        output_dim=y.shape[1],
    )
