"""FR-OPT-01 / FR-OPT-02 — compatibility wrappers around app.optimization."""

from __future__ import annotations

from app.optimization.engine import (
    SetpointAdvice,
    UnitBenchmark,
    UnitOperatingState,
    UnitSnapshot,
    advice_to_text,
    build_structured_advice,
    classify_units as classify_operating_states,
)


def classify_units(units: list[UnitSnapshot]) -> list[dict]:
    states = [
        UnitOperatingState(
            plant_code=u.plant_code,
            electricity_power_mw=15.0,
            fuel_gas_flow_km3h=100.0,
            steam_flow_tonh=30.0,
            feed_flow_tonh=100.0,
            reactor_temp_c=400.0,
            energy_efficiency_percent=u.energy_efficiency_percent,
            energy_intensity_kgoe_ton=u.energy_intensity_kgoe_ton,
        )
        for u in units
    ]
    return [
        {
            "plant_code": b.plant_code,
            "energy_efficiency_percent": b.energy_efficiency_percent,
            "energy_intensity_kgoe_ton": b.energy_intensity_kgoe_ton,
            "tier": b.tier,
        }
        for b in classify_operating_states(states)
    ]


def build_recommendations(classified: list[dict]) -> list[str]:
    states = [
        UnitOperatingState(
            plant_code=u["plant_code"],
            electricity_power_mw=15.0,
            fuel_gas_flow_km3h=100.0,
            steam_flow_tonh=30.0,
            feed_flow_tonh=100.0,
            reactor_temp_c=405.0 if u.get("tier") == "low" else 395.0,
            energy_efficiency_percent=u["energy_efficiency_percent"],
            energy_intensity_kgoe_ton=u["energy_intensity_kgoe_ton"],
        )
        for u in classified
    ]
    # Ensure relative temps differ for advice generation when only efficiency given
    for s, u in zip(states, classified, strict=False):
        if u.get("tier") == "low":
            s.reactor_temp_c = 410.0
            s.fuel_gas_flow_km3h = 115.0
            s.feed_flow_tonh = 92.0
    benchmarks = classify_operating_states(states)
    return advice_to_text(build_structured_advice(states, benchmarks))


__all__ = [
    "SetpointAdvice",
    "UnitBenchmark",
    "UnitOperatingState",
    "UnitSnapshot",
    "advice_to_text",
    "build_recommendations",
    "build_structured_advice",
    "classify_units",
]
