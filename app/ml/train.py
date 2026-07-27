"""Training pipeline: dataset → VSG → ELM/LSTM → registry (E8 trusted gates)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.ml.dataset import (
    MLDataset,
    build_synthetic_dataset,
    load_db_dataset,
    train_test_split,
)
from app.ml.drift import drift_report, feature_reference_stats
from app.ml.elm import train_elm
from app.ml.features import FEATURE_COLUMNS
from app.ml.lstm import train_lstm
from app.ml.metrics import multi_output_mape
from app.ml.physics_calibrate import fit_calibration_from_xy, save_calibration
from app.ml.registry import RegisteredModel, log_to_mlflow, save_local
from app.ml.vsg import augment_with_vsg, merge_real_and_virtual

logger = logging.getLogger(__name__)

ModelKind = Literal["elm", "lstm"]


class TrustedDataError(RuntimeError):
    """Raised when trusted mode lacks sufficient plant data or MAPE gate fails."""


@dataclass
class TrainResult:
    kind: ModelKind
    plant_code: str
    mape: float
    train_size: int
    test_size: int
    vsg_samples: int
    data_source: str
    registered: RegisteredModel
    meets_mape_target: bool
    mlflow_run_id: str | None
    trusted: bool = False
    holdout_temporal: bool = False
    physics_cal_version: str | None = None
    feature_ref: dict[str, Any] | None = None


async def prepare_dataset(
    session: AsyncSession | None,
    plant_code: str,
    settings: Settings,
) -> MLDataset:
    if session is not None:
        db_ds = await load_db_dataset(
            session,
            plant_code,
            limit=settings.ml_train_sample_limit,
            lookback_hours=settings.ml_lookback_hours,
        )
        if db_ds is not None and len(db_ds) >= settings.ml_min_real_samples:
            logger.info("Using TimescaleDB dataset n=%s for %s", len(db_ds), plant_code)
            return db_ds
        if settings.trusted_mode_active or not settings.allow_ml_synthetic():
            have = 0 if db_ds is None else len(db_ds)
            raise TrustedDataError(
                f"Trusted mode requires ≥{settings.ml_min_real_samples} plant samples "
                f"for '{plant_code}' (have {have}); synthetic fallback disabled"
            )
    elif settings.trusted_mode_active or not settings.allow_ml_synthetic():
        raise TrustedDataError(
            "Trusted mode requires a DB session with plant readings; synthetic disabled"
        )

    return build_synthetic_dataset(
        n_samples=settings.ml_synthetic_samples,
        plant_code=plant_code,
        seed=settings.ml_seed,
    )


def _vsg_augment_xy(
    X_train: np.ndarray,
    y_train: np.ndarray,
    settings: Settings,
    *,
    trusted: bool,
    plant_code: str,
) -> tuple[np.ndarray, np.ndarray, int]:
    if trusted and not settings.ml_allow_vsg_in_trusted:
        return X_train, y_train, 0
    if settings.ml_vsg_samples <= 0:
        return X_train, y_train, 0
    frame = pd.DataFrame(X_train, columns=list(FEATURE_COLUMNS))
    from app.ml.features import TARGET_COLUMNS

    for i, col in enumerate(TARGET_COLUMNS):
        frame[col] = y_train[:, i] if y_train.ndim == 2 else y_train
    virtual = augment_with_vsg(
        frame,
        method=settings.ml_vsg_method,
        n_samples=settings.ml_vsg_samples,
        seed=settings.ml_seed,
    )
    merged = merge_real_and_virtual(frame, virtual)
    aug = MLDataset(frame=merged, source="train+vsg", plant_code=plant_code)
    return aug.X, aug.y, len(virtual)


async def train_model(
    *,
    kind: ModelKind,
    plant_code: str = "olefin",
    session: AsyncSession | None = None,
    settings: Settings | None = None,
    calibrate_physics: bool = True,
) -> TrainResult:
    cfg = settings or get_settings()
    trusted = cfg.trusted_mode_active
    dataset = await prepare_dataset(session, plant_code, cfg)

    physics_cal_version = None
    if calibrate_physics and dataset.source == "timescaledb" and len(dataset) >= 20:
        cal = fit_calibration_from_xy(dataset.X, dataset.y, plant_code)
        save_calibration(cal, cfg)
        physics_cal_version = cal.version

    # Temporal holdout for plant data and for LSTM (synthetic is also time-ordered)
    use_temporal = dataset.source == "timescaledb" or kind == "lstm"
    X_train, y_train, X_test, y_test = train_test_split(
        dataset,
        test_ratio=cfg.ml_holdout_ratio if use_temporal else cfg.ml_test_ratio,
        seed=cfg.ml_seed,
        temporal=use_temporal,
    )
    X_train, y_train, n_vsg = _vsg_augment_xy(
        X_train, y_train, cfg, trusted=trusted, plant_code=plant_code
    )
    data_source = (
        f"{dataset.source}+vsg" if n_vsg else dataset.source
    )

    if kind == "elm":
        model = train_elm(X_train, y_train, n_hidden=cfg.ml_elm_hidden, seed=cfg.ml_seed)
        params: dict[str, Any] = {"n_hidden": cfg.ml_elm_hidden}
    else:
        model = train_lstm(
            X_train,
            y_train,
            lookback=cfg.ml_lstm_lookback,
            hidden_dim=cfg.ml_lstm_hidden,
            epochs=cfg.ml_lstm_epochs,
            lr=cfg.ml_lstm_lr,
            seed=cfg.ml_seed,
            prefer_torch=cfg.ml_prefer_torch_lstm,
        )
        params = {
            "lookback": cfg.ml_lstm_lookback,
            "hidden_dim": cfg.ml_lstm_hidden,
            "epochs": cfg.ml_lstm_epochs,
            "lr": cfg.ml_lstm_lr,
            "backend": getattr(model, "backend", "temporal_elm"),
        }

    y_pred = model.predict(X_test)
    n = min(len(y_pred), len(y_test))
    mape_value = multi_output_mape(y_test[-n:], y_pred[-n:])
    feat_ref = feature_reference_stats(X_train)
    metrics: dict[str, Any] = {
        "mape": mape_value,
        "test_size": float(n),
        "holdout_temporal": use_temporal,
        "trusted": trusted,
        "data_source": data_source,
        "feature_ref": feat_ref,
        "physics_cal_version": physics_cal_version,
    }

    meets = mape_value <= cfg.ml_mape_target
    if trusted and not meets:
        raise TrustedDataError(
            f"Trusted train rejected: holdout MAPE {mape_value:.3f} > target {cfg.ml_mape_target}"
        )

    registered = save_local(
        model,
        kind=kind,
        plant_code=plant_code,
        mape_value=mape_value,
        settings=cfg,
        metrics=metrics,
    )
    run_id = log_to_mlflow(
        model,
        kind=kind,
        plant_code=plant_code,
        mape_value=mape_value,
        params=params,
        metrics={k: v for k, v in metrics.items() if isinstance(v, (int, float, bool))},
        settings=cfg,
    )
    if run_id:
        registered.run_id = run_id

    return TrainResult(
        kind=kind,
        plant_code=plant_code,
        mape=round(mape_value, 3),
        train_size=len(X_train),
        test_size=n,
        vsg_samples=n_vsg,
        data_source=data_source,
        registered=registered,
        meets_mape_target=meets,
        mlflow_run_id=run_id,
        trusted=trusted,
        holdout_temporal=use_temporal,
        physics_cal_version=physics_cal_version,
        feature_ref=feat_ref,
    )


def _reference_matrix_from_stats(ref: dict[str, Any]) -> np.ndarray | None:
    """Rebuild approximate reference columns from stored hist/edges."""
    features = ref.get("features") or {}
    cols: list[np.ndarray] = []
    for name in FEATURE_COLUMNS:
        st = features.get(name) or {}
        hist = np.asarray(st.get("hist") or [], dtype=float)
        edges = np.asarray(st.get("edges") or [], dtype=float)
        if hist.size and edges.size == hist.size + 1:
            mids = 0.5 * (edges[:-1] + edges[1:])
            samples: list[float] = []
            for mid, count in zip(mids, hist):
                samples.extend([float(mid)] * max(int(count), 0))
            if samples:
                cols.append(np.asarray(samples, dtype=float))
                continue
        mean = float(st.get("mean", 0.0))
        std = float(st.get("std", 1.0))
        cols.append(np.random.default_rng(0).normal(mean, max(std, 1e-6), size=50))
    if not cols:
        return None
    n = min(len(c) for c in cols)
    return np.column_stack([c[:n] for c in cols])


async def evaluate_drift(
    session: AsyncSession,
    *,
    plant_code: str,
    kind: ModelKind = "elm",
    settings: Settings | None = None,
) -> dict[str, Any]:
    cfg = settings or get_settings()
    registered = load_latest_safe(kind, plant_code, cfg)
    if registered is None:
        return {"status": "no_model", "plant_code": plant_code, "kind": kind}
    ref = (registered.metrics or {}).get("feature_ref")
    if not ref:
        return {"status": "no_feature_ref", "plant_code": plant_code, "kind": kind}

    current = await load_db_dataset(
        session, plant_code, limit=2000, lookback_hours=min(6, cfg.ml_lookback_hours)
    )
    if current is None or len(current) < 10:
        return {"status": "insufficient_current_data", "plant_code": plant_code}

    ref_X = _reference_matrix_from_stats(ref)
    if ref_X is None:
        return {"status": "bad_feature_ref", "plant_code": plant_code}
    report = drift_report(ref_X, current.X, threshold=cfg.ml_drift_psi_threshold)
    report.update(
        {
            "status": "ok",
            "plant_code": plant_code,
            "kind": kind,
            "model_version": registered.version,
            "holdout_mape": registered.mape,
            "trusted": bool((registered.metrics or {}).get("trusted")),
            "data_source": (registered.metrics or {}).get("data_source"),
        }
    )
    return report


def model_trust_status(
    *,
    plant_code: str,
    kind: ModelKind = "elm",
    settings: Settings | None = None,
) -> dict[str, Any]:
    cfg = settings or get_settings()
    registered = load_latest_safe(kind, plant_code, cfg)
    trusted_mode = cfg.trusted_mode_active
    if registered is None:
        return {
            "status": "unavailable",
            "plant_code": plant_code,
            "kind": kind,
            "trusted_mode": trusted_mode,
            "allow_synthetic": cfg.allow_ml_synthetic(),
            "allow_physics_fallback": cfg.allow_ml_physics_fallback(),
            "reason": "no_registered_model",
        }
    meta = registered.metrics or {}
    mape_ok = registered.mape <= cfg.ml_mape_target
    plant_data = "timescaledb" in str(meta.get("data_source", ""))
    trust_ok = (not trusted_mode) or (plant_data and mape_ok)
    return {
        "status": "trusted" if trust_ok and mape_ok else "registered",
        "plant_code": plant_code,
        "kind": kind,
        "trusted_mode": trusted_mode,
        "model_version": registered.version,
        "holdout_mape": registered.mape,
        "meets_mape_target": mape_ok,
        "holdout_temporal": bool(meta.get("holdout_temporal")),
        "data_source": meta.get("data_source"),
        "physics_cal_version": meta.get("physics_cal_version"),
        "allow_synthetic": cfg.allow_ml_synthetic(),
        "allow_physics_fallback": cfg.allow_ml_physics_fallback(),
        "trust_ok": trust_ok,
    }


def load_latest_safe(kind: ModelKind, plant_code: str, settings: Settings):
    from app.ml.registry import load_latest

    return load_latest(kind, plant_code, settings)
