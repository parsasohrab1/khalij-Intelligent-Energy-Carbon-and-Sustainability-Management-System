"""Phase 3 — VSG, ELM/LSTM training, MAPE and latency targets."""

import numpy as np
import pytest

from app.core.config import get_settings
from app.ml.dataset import build_synthetic_dataset
from app.ml.metrics import mape, multi_output_mape
from app.ml.registry import load_latest
from app.ml.serve import predict_with_model
from app.ml.train import train_model
from app.ml.vsg import augment_with_vsg
from app.services.prediction import predict_energy, simulate_what_if


@pytest.fixture(autouse=True)
def _isolated_model_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ML_MODEL_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("ML_SYNTHETIC_SAMPLES", "400")
    monkeypatch.setenv("ML_VSG_SAMPLES", "80")
    monkeypatch.setenv("ML_LSTM_EPOCHS", "8")
    monkeypatch.setenv("ML_ELM_HIDDEN", "48")
    monkeypatch.setenv("MLFLOW_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_vsg_from_real_data():
    ds = build_synthetic_dataset(n_samples=100, plant_code="olefin", seed=1)
    samples = augment_with_vsg(ds.frame, method="mc", n_samples=30, seed=1)
    assert len(samples) == 30
    assert "energy_intensity_kgoe_ton" in samples[0]


@pytest.mark.asyncio
async def test_train_elm_meets_mape_target():
    result = await train_model(kind="elm", plant_code="olefin", session=None)
    assert result.mape <= 5.0
    assert result.meets_mape_target
    assert load_latest("elm", "olefin") is not None


@pytest.mark.asyncio
async def test_train_lstm_and_predict_latency():
    result = await train_model(kind="lstm", plant_code="olefin", session=None)
    assert result.mape <= 5.0
    pred = predict_with_model(
        features={
            "electricity_power_mw": 15.0,
            "fuel_gas_flow_km3h": 100.0,
            "steam_flow_tonh": 30.0,
            "feed_flow_tonh": 100.0,
            "reactor_temp_c": 400.0,
        },
        horizon_minutes=60,
        model="lstm",
        plant_code="olefin",
    )
    assert pred.latency_ms < 3000
    assert pred.source == "ml_model"
    assert pred.predicted_energy_kwh > 0


@pytest.mark.asyncio
async def test_elm_predict_under_3s_with_model():
    await train_model(kind="elm", plant_code="olefin", session=None)
    pred = predict_energy(
        horizon_minutes=60,
        model="elm",
        plant_code="olefin",
        electricity_power_mw=15,
        fuel_gas_flow_km3h=100,
        steam_flow_tonh=30,
        feed_flow_tonh=100,
        reactor_temp_c=400,
    )
    assert pred.latency_ms < 3000
    assert pred.mape_estimate <= 5.0
    assert pred.source == "ml_model"


def test_what_if_uses_model_fields():
    out = simulate_what_if(
        reactor_temp_c=410,
        feed_flow_tonh=105,
        fuel_gas_flow_km3h=95,
        plant_code="olefin",
        model="elm",
    )
    assert out["estimated_energy_intensity_kgoe_ton"] > 0


def test_mape_metric():
    y_true = np.array([100.0, 200.0, 300.0])
    y_pred = np.array([102.0, 196.0, 309.0])
    assert mape(y_true, y_pred) < 5.0
    assert (
        multi_output_mape(
            np.column_stack([y_true, y_true]),
            np.column_stack([y_pred, y_pred]),
        )
        < 5.0
    )
