"""Feature / target definitions for energy prediction (FR-ML-02)."""

from __future__ import annotations

FEATURE_COLUMNS = (
    "electricity_power_mw",
    "fuel_gas_flow_km3h",
    "steam_flow_tonh",
    "feed_flow_tonh",
    "reactor_temp_c",
)

TARGET_COLUMNS = (
    "energy_intensity_kgoe_ton",
    "carbon_emission_kgco2_ton",
)

KGOE_TO_KWH = 11.63


def intensity_to_energy_kwh(
    intensity_kgoe_ton: float,
    feed_flow_tonh: float,
    horizon_minutes: float,
) -> float:
    hours = horizon_minutes / 60.0
    return float(intensity_kgoe_ton * feed_flow_tonh * hours * KGOE_TO_KWH)
