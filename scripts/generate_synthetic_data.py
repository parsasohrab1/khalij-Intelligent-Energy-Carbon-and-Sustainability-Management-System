"""Synthetic petrochemical energy/carbon dataset generator (SRS sample).

Produces 10,000 one-second records for olefin/PTA-style process variables.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd


def generate(
    num_records: int = 10_000,
    start_time: datetime | None = None,
    seed: int = 42,
    output_path: str | Path = "data/raw/petrochemical_energy_carbon_data_10k.csv",
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    start_time = start_time or datetime(2026, 7, 22, 8, 0, 0)
    timestamps = [start_time + timedelta(seconds=i) for i in range(num_records)]
    t = np.linspace(0, 10 * np.pi, num_records)

    electricity_power = 15 + 5 * np.sin(t * 0.2) + 0.005 * np.arange(num_records)
    electricity_power = electricity_power + rng.normal(0, 0.5, num_records)
    electricity_power = np.clip(electricity_power, 5, 25)

    fuel_gas_flow = 100 + 30 * np.sin(t * 0.15 + 1.5) + rng.normal(0, 3, num_records)
    fuel_gas_flow = np.clip(fuel_gas_flow, 50, 150)

    steam_flow = 30 + 10 * np.sin(t * 0.25 + 0.8) + rng.normal(0, 1.5, num_records)
    steam_flow = np.clip(steam_flow, 10, 50)

    feed_flow = 100 + 15 * np.sin(t * 0.1 + 2.0) + rng.normal(0, 2, num_records)
    feed_flow = np.clip(feed_flow, 80, 120)

    reactor_temp = 400 + 15 * np.sin(t * 0.2 + 1.0) + rng.normal(0, 1, num_records)
    reactor_temp = np.clip(reactor_temp, 380, 420)

    energy_intensity = (
        600
        + 0.5 * fuel_gas_flow
        + 2 * steam_flow
        - 0.1 * feed_flow
        + 0.3 * reactor_temp
        + rng.normal(0, 10, num_records)
    )
    energy_intensity = np.clip(energy_intensity, 500, 800)

    carbon_emission = (
        0.2 * fuel_gas_flow
        + 0.3 * steam_flow
        + 0.05 * electricity_power
        + rng.normal(0, 2, num_records)
    )
    carbon_emission = np.clip(carbon_emission, 20, 80)

    energy_efficiency = 85 - 0.025 * (energy_intensity - 500) + rng.normal(0, 1, num_records)
    energy_efficiency = np.clip(energy_efficiency, 60, 92)

    df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "electricity_power_mw": np.round(electricity_power, 2),
            "fuel_gas_flow_km3h": np.round(fuel_gas_flow, 2),
            "steam_flow_tonh": np.round(steam_flow, 2),
            "feed_flow_tonh": np.round(feed_flow, 2),
            "reactor_temp_c": np.round(reactor_temp, 2),
            "energy_intensity_kgoe_ton": np.round(energy_intensity, 2),
            "carbon_emission_kgco2_ton": np.round(carbon_emission, 2),
            "energy_efficiency_percent": np.round(energy_efficiency, 2),
        }
    )

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return df


def main() -> None:
    df = generate()
    print(f"Saved {len(df):,} records × {len(df.columns)} columns")
    print(df.head())
    print(df.describe())


if __name__ == "__main__":
    main()
