"""E8 Trusted Models — plant-only gates, temporal holdout, drift, no fake MAPE."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.ml.dataset import build_synthetic_dataset, train_test_split
from app.ml.drift import compute_psi, drift_report, feature_reference_stats
from app.ml.features import FEATURE_COLUMNS
from app.ml.lstm import build_temporal_windows, train_lstm
from app.ml.serve import ModelUnavailableError, predict_with_model
from app.ml.train import TrustedDataError, model_trust_status, train_model

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("ML_MODEL_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("ML_SYNTHETIC_SAMPLES", "400")
    monkeypatch.setenv("ML_VSG_SAMPLES", "40")
    monkeypatch.setenv("ML_LSTM_EPOCHS", "6")
    monkeypatch.setenv("ML_ELM_HIDDEN", "48")
    monkeypatch.setenv("MLFLOW_ENABLED", "false")
    monkeypatch.setenv("ML_TRUSTED_MODE", "false")
    monkeypatch.setenv("PLANT_CONNECT", "false")
    monkeypatch.setenv("ML_PHYSICS_SCALE_PATH", str(tmp_path / "physics_cal.yaml"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_temporal_split_keeps_order():
    ds = build_synthetic_dataset(n_samples=100, seed=7)
    X_tr, y_tr, X_te, y_te = train_test_split(ds, test_ratio=0.2, temporal=True)
    assert len(X_tr) + len(X_te) == 100
    # last train row should precede first test in original order
    assert np.allclose(X_tr[-1], ds.X[len(X_tr) - 1])
    assert np.allclose(X_te[0], ds.X[len(X_tr)])


def test_lstm_uses_true_windows_not_stub():
    ds = build_synthetic_dataset(n_samples=120, seed=3)
    X_seq, y_out, X_flat = build_temporal_windows(ds.X, ds.y, lookback=8)
    assert X_seq.ndim == 3
    assert X_seq.shape[1] == 8
    assert X_flat.shape[1] == 8 * len(FEATURE_COLUMNS)
    # consecutive windows differ when process data drifts
    assert not np.allclose(X_seq[0], X_seq[min(20, len(X_seq) - 1)])
    model = train_lstm(ds.X, ds.y, lookback=8, epochs=5, prefer_torch=False, seed=3)
    assert model.backend == "temporal_elm"
    pred = model.predict(ds.X[-16:])
    assert pred.shape[0] >= 1


def test_psi_and_drift_report():
    rng = np.random.default_rng(0)
    ref = rng.normal(0, 1, size=(200, len(FEATURE_COLUMNS)))
    same = rng.normal(0, 1, size=(200, len(FEATURE_COLUMNS)))
    shifted = rng.normal(3, 1, size=(200, len(FEATURE_COLUMNS)))
    assert compute_psi(ref[:, 0], same[:, 0]) < 0.2
    assert compute_psi(ref[:, 0], shifted[:, 0]) > 0.2
    report = drift_report(ref, shifted, threshold=0.2)
    assert report["drift_alert"] is True


@pytest.mark.asyncio
async def test_trusted_mode_blocks_synthetic(monkeypatch, tmp_path):
    monkeypatch.setenv("ML_TRUSTED_MODE", "true")
    monkeypatch.setenv("ML_MODEL_DIR", str(tmp_path / "models"))
    get_settings.cache_clear()
    with pytest.raises(TrustedDataError, match="synthetic"):
        await train_model(kind="elm", plant_code="olefin", session=None)
    get_settings.cache_clear()


def test_trusted_mode_blocks_physics_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("ML_TRUSTED_MODE", "true")
    monkeypatch.setenv("ML_MODEL_DIR", str(tmp_path / "models_empty"))
    get_settings.cache_clear()
    with pytest.raises(ModelUnavailableError, match="physics fallback"):
        predict_with_model(
            features={
                "electricity_power_mw": 15.0,
                "fuel_gas_flow_km3h": 100.0,
                "steam_flow_tonh": 30.0,
                "feed_flow_tonh": 100.0,
                "reactor_temp_c": 400.0,
            },
            model="elm",
            plant_code="olefin",
        )
    get_settings.cache_clear()


def test_physics_fallback_has_no_fake_mape(monkeypatch, tmp_path):
    monkeypatch.setenv("ML_TRUSTED_MODE", "false")
    monkeypatch.setenv("ML_MODEL_DIR", str(tmp_path / "models_empty2"))
    get_settings.cache_clear()
    pred = predict_with_model(
        features={
            "electricity_power_mw": 15.0,
            "fuel_gas_flow_km3h": 100.0,
            "steam_flow_tonh": 30.0,
            "feed_flow_tonh": 100.0,
            "reactor_temp_c": 400.0,
        },
        model="elm",
        plant_code="olefin",
    )
    assert pred.source == "physics_fallback"
    assert pred.mape_estimate is None
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_demo_train_still_works_when_not_trusted():
    result = await train_model(kind="elm", plant_code="olefin", session=None)
    assert result.meets_mape_target
    assert result.data_source == "synthetic" or "synthetic" in result.data_source
    trust = model_trust_status(plant_code="olefin", kind="elm")
    assert trust["status"] in {"trusted", "registered"}
    assert trust["holdout_mape"] is not None


def test_trust_api_endpoints(monkeypatch, tmp_path):
    monkeypatch.setenv("ML_TRUSTED_MODE", "true")
    get_settings.cache_clear()
    r = client.get("/api/v1/ml/trust/olefin/elm")
    assert r.status_code == 200
    body = r.json()
    assert body["trusted_mode"] is True
    assert body["allow_synthetic"] is False
    assert body["allow_physics_fallback"] is False

    r2 = client.get("/api/v1/ml/calibrate/olefin")
    assert r2.status_code == 200
    assert "energy_scale" in r2.json()
    get_settings.cache_clear()


def test_feature_reference_stats_shape():
    ds = build_synthetic_dataset(n_samples=50, seed=1)
    ref = feature_reference_stats(ds.X)
    assert ref["n"] == 50
    assert set(ref["features"]) == set(FEATURE_COLUMNS)
