"""FR-ML-02 / FR-ML-03 — compatibility wrappers around app.ml serve layer."""

from __future__ import annotations

from app.ml.serve import PredictionResult, predict_with_model, simulate_what_if_ml
from app.services.physics import carbon_emission_intensity, energy_efficiency, energy_intensity


def predict_energy(
    *,
    electricity_power_mw: float = 15.0,
    fuel_gas_flow_km3h: float = 100.0,
    steam_flow_tonh: float = 30.0,
    feed_flow_tonh: float = 100.0,
    reactor_temp_c: float = 400.0,
    horizon_minutes: int = 60,
    model: str = "elm",
    plant_code: str = "olefin",
) -> PredictionResult:
    features = {
        "electricity_power_mw": electricity_power_mw,
        "fuel_gas_flow_km3h": fuel_gas_flow_km3h,
        "steam_flow_tonh": steam_flow_tonh,
        "feed_flow_tonh": feed_flow_tonh,
        "reactor_temp_c": reactor_temp_c,
    }
    return predict_with_model(
        features=features,
        horizon_minutes=horizon_minutes,
        model=model,  # type: ignore[arg-type]
        plant_code=plant_code,
    )


def simulate_what_if(
    *,
    reactor_temp_c: float,
    feed_flow_tonh: float,
    fuel_gas_flow_km3h: float,
    steam_flow_tonh: float = 30.0,
    electricity_power_mw: float = 15.0,
    plant_code: str = "olefin",
    model: str = "elm",
) -> dict[str, float]:
    result = simulate_what_if_ml(
        plant_code=plant_code,
        reactor_temp_c=reactor_temp_c,
        feed_flow_tonh=feed_flow_tonh,
        fuel_gas_flow_km3h=fuel_gas_flow_km3h,
        steam_flow_tonh=steam_flow_tonh,
        electricity_power_mw=electricity_power_mw,
        model=model,  # type: ignore[arg-type]
    )
    return {
        "estimated_energy_intensity_kgoe_ton": result["estimated_energy_intensity_kgoe_ton"],
        "estimated_carbon_emission_kgco2_ton": result["estimated_carbon_emission_kgco2_ton"],
        "estimated_efficiency_percent": result["estimated_efficiency_percent"],
    }


__all__ = [
    "PredictionResult",
    "predict_energy",
    "simulate_what_if",
    "energy_intensity",
    "carbon_emission_intensity",
    "energy_efficiency",
]
