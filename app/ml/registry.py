"""MLflow + local model registry for ELM/LSTM artifacts."""

from __future__ import annotations

import json
import logging
import pickle
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from app.core.config import Settings, get_settings
from app.ml.elm import ELMModel
from app.ml.lstm import LSTMModel

logger = logging.getLogger(__name__)

ModelKind = Literal["elm", "lstm"]


@dataclass
class RegisteredModel:
    kind: ModelKind
    model: ELMModel | LSTMModel
    version: str
    run_id: str | None
    mape: float
    artifact_path: str
    plant_code: str
    registered_at: str


def _local_dir(settings: Settings) -> Path:
    path = Path(settings.ml_model_dir)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_local(
    model: ELMModel | LSTMModel,
    *,
    kind: ModelKind,
    plant_code: str,
    mape_value: float,
    settings: Settings | None = None,
    metrics: dict[str, Any] | None = None,
) -> RegisteredModel:
    cfg = settings or get_settings()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    version = f"{kind}-{plant_code}-{stamp}"
    out_dir = _local_dir(cfg) / plant_code / kind
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / f"{version}.pkl"
    meta_path = out_dir / f"{version}.json"
    latest_path = out_dir / "latest.json"

    with model_path.open("wb") as fh:
        pickle.dump(model, fh)

    meta = {
        "kind": kind,
        "plant_code": plant_code,
        "version": version,
        "mape": mape_value,
        "artifact_path": str(model_path),
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics or {},
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    latest_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return RegisteredModel(
        kind=kind,
        model=model,
        version=version,
        run_id=None,
        mape=mape_value,
        artifact_path=str(model_path),
        plant_code=plant_code,
        registered_at=meta["registered_at"],
    )


def log_to_mlflow(
    model: ELMModel | LSTMModel,
    *,
    kind: ModelKind,
    plant_code: str,
    mape_value: float,
    params: dict[str, Any],
    metrics: dict[str, float],
    settings: Settings | None = None,
) -> str | None:
    cfg = settings or get_settings()
    if not cfg.mlflow_enabled:
        return None
    try:
        import mlflow
    except ImportError:
        logger.warning("mlflow not installed; skipping remote logging")
        return None

    try:
        mlflow.set_tracking_uri(cfg.mlflow_tracking_uri)
        mlflow.set_experiment(cfg.mlflow_experiment_name)
        with mlflow.start_run(run_name=f"{kind}-{plant_code}") as run:
            mlflow.log_params({**params, "plant_code": plant_code, "model_kind": kind})
            mlflow.log_metrics({**metrics, "mape": mape_value})
            local = save_local(
                model,
                kind=kind,
                plant_code=plant_code,
                mape_value=mape_value,
                settings=cfg,
                metrics=metrics,
            )
            mlflow.log_artifact(local.artifact_path)
            return run.info.run_id
    except Exception:
        logger.exception("MLflow logging failed; local artifact kept")
        return None


def load_latest(
    kind: ModelKind,
    plant_code: str,
    settings: Settings | None = None,
) -> RegisteredModel | None:
    cfg = settings or get_settings()
    latest_path = _local_dir(cfg) / plant_code / kind / "latest.json"
    if not latest_path.exists():
        return None
    meta = json.loads(latest_path.read_text(encoding="utf-8"))
    with Path(meta["artifact_path"]).open("rb") as fh:
        model = pickle.load(fh)
    return RegisteredModel(
        kind=kind,
        model=model,
        version=meta["version"],
        run_id=meta.get("run_id"),
        mape=float(meta["mape"]),
        artifact_path=meta["artifact_path"],
        plant_code=plant_code,
        registered_at=meta["registered_at"],
    )
