"""Training pipeline: dataset → VSG → ELM/LSTM → MLflow/local registry."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.ml.dataset import (
    MLDataset,
    build_synthetic_dataset,
    load_db_dataset,
    train_test_split,
)
from app.ml.elm import train_elm
from app.ml.lstm import train_lstm
from app.ml.metrics import multi_output_mape
from app.ml.registry import RegisteredModel, log_to_mlflow, save_local
from app.ml.vsg import augment_with_vsg, merge_real_and_virtual

logger = logging.getLogger(__name__)

ModelKind = Literal["elm", "lstm"]


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
    return build_synthetic_dataset(
        n_samples=settings.ml_synthetic_samples,
        plant_code=plant_code,
        seed=settings.ml_seed,
    )


def _augment_frame(frame: pd.DataFrame, settings: Settings) -> tuple[pd.DataFrame, int]:
    virtual = augment_with_vsg(
        frame,
        method=settings.ml_vsg_method,
        n_samples=settings.ml_vsg_samples,
        seed=settings.ml_seed,
    )
    merged = merge_real_and_virtual(frame, virtual)
    return merged, len(virtual)


async def train_model(
    *,
    kind: ModelKind,
    plant_code: str = "olefin",
    session: AsyncSession | None = None,
    settings: Settings | None = None,
) -> TrainResult:
    cfg = settings or get_settings()
    dataset = await prepare_dataset(session, plant_code, cfg)
    augmented, n_vsg = _augment_frame(dataset.frame, cfg)
    aug_ds = MLDataset(frame=augmented, source=f"{dataset.source}+vsg", plant_code=plant_code)

    X_train, y_train, X_test, y_test = train_test_split(
        aug_ds, test_ratio=cfg.ml_test_ratio, seed=cfg.ml_seed
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
        )
        params = {
            "lookback": cfg.ml_lstm_lookback,
            "hidden_dim": cfg.ml_lstm_hidden,
            "epochs": cfg.ml_lstm_epochs,
            "lr": cfg.ml_lstm_lr,
        }

    y_pred = model.predict(X_test)
    mape_value = multi_output_mape(y_test, y_pred)
    metrics = {"mape": mape_value, "test_size": float(len(X_test))}

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
        metrics=metrics,
        settings=cfg,
    )
    if run_id:
        registered.run_id = run_id

    return TrainResult(
        kind=kind,
        plant_code=plant_code,
        mape=round(mape_value, 3),
        train_size=len(X_train),
        test_size=len(X_test),
        vsg_samples=n_vsg,
        data_source=aug_ds.source,
        registered=registered,
        meets_mape_target=mape_value <= cfg.ml_mape_target,
        mlflow_run_id=run_id,
    )
