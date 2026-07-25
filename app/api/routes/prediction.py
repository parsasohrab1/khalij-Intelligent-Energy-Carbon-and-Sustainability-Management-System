"""FR-ML-01 / FR-ML-02 / FR-ML-03 — prediction, training, VSG, what-if."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_action
from app.core.config import get_settings
from app.db.session import get_db
from app.ml.dataset import load_db_dataset
from app.ml.registry import load_latest
from app.ml.serve import persist_prediction, predict_with_model, resolve_features, simulate_what_if_ml
from app.ml.train import train_model
from app.schemas import (
    ModelInfoOut,
    PredictionRequest,
    PredictionResponse,
    TrainRequest,
    TrainResponse,
    VSGRequest,
    VSGResponse,
    WhatIfRequest,
    WhatIfResponse,
)
from app.services.vsg import generate_virtual_samples

router = APIRouter(prefix="/ml", tags=["prediction"])


@router.post("/predict", response_model=PredictionResponse)
async def predict(
    body: PredictionRequest,
    db: AsyncSession = Depends(get_db),
) -> PredictionResponse:
    features = await resolve_features(db, body.plant_code)
    result = predict_with_model(
        features=features,
        horizon_minutes=body.horizon_minutes,
        model=body.model,
        plant_code=body.plant_code,
    )
    if result.latency_ms >= get_settings().ml_max_latency_ms:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Prediction exceeded latency budget ({result.latency_ms} ms)",
        )
    try:
        await persist_prediction(
            db,
            plant_code=body.plant_code,
            result=result,
            horizon_minutes=body.horizon_minutes,
        )
    except Exception:
        # Persistence is best-effort; prediction still returned
        pass

    note = (
        f"Served from {result.source}"
        + (f" version={result.model_version}" if result.model_version else "")
    )
    return PredictionResponse(
        plant_code=body.plant_code,
        horizon_minutes=body.horizon_minutes,
        model=result.model,
        predicted_energy_kwh=result.predicted_energy_kwh,
        predicted_carbon_kgco2=result.predicted_carbon_kgco2,
        latency_ms=result.latency_ms,
        mape_estimate=result.mape_estimate,
        model_version=result.model_version,
        source=result.source,
        note=note,
    )


@router.post("/what-if", response_model=WhatIfResponse)
async def what_if(body: WhatIfRequest) -> WhatIfResponse:
    sim = simulate_what_if_ml(
        plant_code=body.plant_code,
        reactor_temp_c=body.reactor_temp_c,
        feed_flow_tonh=body.feed_flow_tonh,
        fuel_gas_flow_km3h=body.fuel_gas_flow_km3h,
        steam_flow_tonh=body.steam_flow_tonh,
        electricity_power_mw=body.electricity_power_mw,
        model=body.model if hasattr(body, "model") else "elm",
    )
    return WhatIfResponse(
        plant_code=body.plant_code,
        estimated_energy_intensity_kgoe_ton=sim["estimated_energy_intensity_kgoe_ton"],
        estimated_carbon_emission_kgco2_ton=sim["estimated_carbon_emission_kgco2_ton"],
        estimated_efficiency_percent=sim["estimated_efficiency_percent"],
        model=sim.get("model"),
        model_version=sim.get("model_version"),
        source=sim.get("source"),
    )


@router.post("/vsg", response_model=VSGResponse)
async def virtual_sample_generation(
    body: VSGRequest,
    db: AsyncSession = Depends(get_db),
) -> VSGResponse:
    real_frame = None
    plant_code = body.plant_code if hasattr(body, "plant_code") else "olefin"
    try:
        ds = await load_db_dataset(db, plant_code, limit=2000, lookback_hours=24)
        if ds is not None and len(ds) > 10:
            real_frame = ds.frame
    except Exception:
        real_frame = None

    samples = generate_virtual_samples(
        method=body.method,
        n_samples=body.n_samples,
        seed=body.seed,
        real_frame=real_frame,
    )
    return VSGResponse(
        method=body.method,
        n_samples=len(samples),
        samples=samples,
        source="empirical" if real_frame is not None else "uniform_bounds",
    )


@router.post("/train", response_model=TrainResponse)
async def train(
    body: TrainRequest,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_action("train")),
) -> TrainResponse:
    result = await train_model(
        kind=body.model,
        plant_code=body.plant_code,
        session=db,
        settings=get_settings(),
    )
    return TrainResponse(
        plant_code=result.plant_code,
        model=result.kind,
        mape=result.mape,
        meets_mape_target=result.meets_mape_target,
        train_size=result.train_size,
        test_size=result.test_size,
        vsg_samples=result.vsg_samples,
        data_source=result.data_source,
        model_version=result.registered.version,
        mlflow_run_id=result.mlflow_run_id,
        artifact_path=result.registered.artifact_path,
    )


@router.get("/models/{plant_code}/{model}", response_model=ModelInfoOut)
async def get_model_info(plant_code: str, model: str) -> ModelInfoOut:
    if model not in {"elm", "lstm"}:
        raise HTTPException(status_code=400, detail="model must be elm or lstm")
    registered = load_latest(model, plant_code)  # type: ignore[arg-type]
    if registered is None:
        raise HTTPException(status_code=404, detail="No registered model found")
    return ModelInfoOut(
        plant_code=plant_code,
        model=model,
        version=registered.version,
        mape=registered.mape,
        artifact_path=registered.artifact_path,
        registered_at=registered.registered_at,
        mlflow_run_id=registered.run_id,
    )
