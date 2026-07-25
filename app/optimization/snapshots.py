"""Load unit operating states for optimization (DB first, simulator fallback)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.opcua_client import read_opcua_plant
from app.optimization.engine import UnitOperatingState
from app.repositories import sensors as sensor_repo
from app.services.physics import enrich_reading


async def load_unit_state(
    session: AsyncSession | None,
    plant_code: str,
) -> UnitOperatingState:
    if session is not None:
        latest = await sensor_repo.get_latest_reading(session, plant_code)
        if latest is not None:
            _, reading = latest
            base = {
                "electricity_power_mw": float(reading.electricity_power_mw or 15.0),
                "fuel_gas_flow_km3h": float(reading.fuel_gas_flow_km3h or 100.0),
                "steam_flow_tonh": float(reading.steam_flow_tonh or 30.0),
                "feed_flow_tonh": float(reading.feed_flow_tonh or 100.0),
                "reactor_temp_c": float(reading.reactor_temp_c or 400.0),
            }
            derived = {
                "energy_intensity_kgoe_ton": float(
                    reading.energy_intensity_kgoe_ton
                    or enrich_reading(**base)["energy_intensity_kgoe_ton"]
                ),
                "energy_efficiency_percent": float(
                    reading.energy_efficiency_percent
                    or enrich_reading(**base)["energy_efficiency_percent"]
                ),
                "carbon_emission_kgco2_ton": (
                    float(reading.carbon_emission_kgco2_ton)
                    if reading.carbon_emission_kgco2_ton is not None
                    else None
                ),
            }
            return UnitOperatingState(
                plant_code=plant_code,
                pressure_bar=float(reading.pressure_bar) if reading.pressure_bar else None,
                **base,
                **derived,
            )

    snap = await read_opcua_plant(plant_code)
    return UnitOperatingState(
        plant_code=plant_code,
        electricity_power_mw=float(snap["electricity_power_mw"]),
        fuel_gas_flow_km3h=float(snap["fuel_gas_flow_km3h"]),
        steam_flow_tonh=float(snap["steam_flow_tonh"]),
        feed_flow_tonh=float(snap["feed_flow_tonh"]),
        reactor_temp_c=float(snap["reactor_temp_c"]),
        energy_efficiency_percent=float(snap["energy_efficiency_percent"]),
        energy_intensity_kgoe_ton=float(snap["energy_intensity_kgoe_ton"]),
        carbon_emission_kgco2_ton=float(snap.get("carbon_emission_kgco2_ton") or 0),
        pressure_bar=float(snap["pressure_bar"]) if snap.get("pressure_bar") is not None else None,
    )


async def load_unit_states(
    session: AsyncSession | None,
    plant_codes: list[str],
) -> list[UnitOperatingState]:
    states: list[UnitOperatingState] = []
    for i, code in enumerate(plant_codes):
        state = await load_unit_state(session, code)
        # If two units share identical sim snapshot, nudge secondary for demo benchmarking
        if i > 0 and session is None:
            factor = 1.0 + 0.08 * i
            base = {
                "electricity_power_mw": state.electricity_power_mw * factor,
                "fuel_gas_flow_km3h": state.fuel_gas_flow_km3h * factor,
                "steam_flow_tonh": state.steam_flow_tonh * factor,
                "feed_flow_tonh": state.feed_flow_tonh,
                "reactor_temp_c": state.reactor_temp_c + 2.0 * i,
            }
            derived = enrich_reading(**base)
            state = UnitOperatingState(
                plant_code=code,
                pressure_bar=state.pressure_bar,
                **base,
                energy_efficiency_percent=derived["energy_efficiency_percent"],
                energy_intensity_kgoe_ton=derived["energy_intensity_kgoe_ton"],
                carbon_emission_kgco2_ton=derived["carbon_emission_kgco2_ton"],
            )
        states.append(state)
    return states
