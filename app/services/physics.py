"""Process physics helpers shared by prediction, what-if, and synthetic data.

Formulas mirror the SRS synthetic generator relationships.
"""

from __future__ import annotations

import numpy as np


def energy_intensity(
    fuel_gas_flow_km3h: float,
    steam_flow_tonh: float,
    feed_flow_tonh: float,
    reactor_temp_c: float,
) -> float:
    value = (
        600.0
        + 0.5 * fuel_gas_flow_km3h
        + 2.0 * steam_flow_tonh
        - 0.1 * feed_flow_tonh
        + 0.3 * reactor_temp_c
    )
    return float(np.clip(value, 500.0, 800.0))


def carbon_emission_intensity(
    fuel_gas_flow_km3h: float,
    steam_flow_tonh: float,
    electricity_power_mw: float,
) -> float:
    """kg CO2 per ton product (SRS synthetic relationship)."""
    value = (
        0.2 * fuel_gas_flow_km3h
        + 0.3 * steam_flow_tonh
        + 0.05 * electricity_power_mw
    )
    return float(np.clip(value, 20.0, 80.0))


def energy_efficiency(energy_intensity_kgoe_ton: float) -> float:
    value = 85.0 - 0.025 * (energy_intensity_kgoe_ton - 500.0)
    return float(np.clip(value, 60.0, 92.0))


def enrich_reading(
    *,
    electricity_power_mw: float,
    fuel_gas_flow_km3h: float,
    steam_flow_tonh: float,
    feed_flow_tonh: float,
    reactor_temp_c: float,
) -> dict[str, float]:
    ei = energy_intensity(fuel_gas_flow_km3h, steam_flow_tonh, feed_flow_tonh, reactor_temp_c)
    ce = carbon_emission_intensity(fuel_gas_flow_km3h, steam_flow_tonh, electricity_power_mw)
    return {
        "energy_intensity_kgoe_ton": round(ei, 2),
        "carbon_emission_kgco2_ton": round(ce, 2),
        "energy_efficiency_percent": round(energy_efficiency(ei), 2),
    }
