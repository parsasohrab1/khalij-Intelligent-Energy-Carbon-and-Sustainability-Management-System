"""Simulate recommendation impact before applying (Phase 4)."""

from __future__ import annotations

from dataclasses import dataclass

from app.ml.serve import simulate_what_if_ml
from app.optimization.engine import SetpointAdvice, UnitOperatingState


@dataclass
class AdviceSimulation:
    plant_code: str
    before_intensity: float
    after_intensity: float
    before_efficiency: float
    after_efficiency: float
    before_carbon_intensity: float
    after_carbon_intensity: float
    intensity_delta: float
    efficiency_delta_pp: float
    carbon_delta: float
    model: str | None
    source: str | None


def simulate_advice(
    state: UnitOperatingState,
    advice: SetpointAdvice,
    *,
    model: str = "elm",
) -> AdviceSimulation:
    proposed = advice.proposed
    after = simulate_what_if_ml(
        plant_code=state.plant_code,
        reactor_temp_c=proposed["reactor_temp_c"],
        feed_flow_tonh=proposed["feed_flow_tonh"],
        fuel_gas_flow_km3h=proposed["fuel_gas_flow_km3h"],
        steam_flow_tonh=proposed["steam_flow_tonh"],
        electricity_power_mw=proposed.get(
            "electricity_power_mw", state.electricity_power_mw
        ),
        model=model,  # type: ignore[arg-type]
    )
    before_carbon = state.carbon_emission_kgco2_ton or 0.0
    after_intensity = after["estimated_energy_intensity_kgoe_ton"]
    after_eff = after["estimated_efficiency_percent"]
    after_carbon = after["estimated_carbon_emission_kgco2_ton"]
    return AdviceSimulation(
        plant_code=state.plant_code,
        before_intensity=state.energy_intensity_kgoe_ton,
        after_intensity=after_intensity,
        before_efficiency=state.energy_efficiency_percent,
        after_efficiency=after_eff,
        before_carbon_intensity=before_carbon,
        after_carbon_intensity=after_carbon,
        intensity_delta=round(after_intensity - state.energy_intensity_kgoe_ton, 2),
        efficiency_delta_pp=round(after_eff - state.energy_efficiency_percent, 2),
        carbon_delta=round(after_carbon - before_carbon, 2),
        model=after.get("model"),
        source=after.get("source"),
    )
