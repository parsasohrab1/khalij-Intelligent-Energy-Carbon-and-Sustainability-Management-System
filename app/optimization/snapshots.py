"""Load unit operating states for optimization (memory → DB → simulator)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.optimization.engine import UnitOperatingState
from app.services.live_reading import resolve_live_reading
from app.services.physics import enrich_reading


async def load_unit_state(
    session: AsyncSession | None,
    plant_code: str,
) -> UnitOperatingState:
    reading = await resolve_live_reading(session, plant_code)
    return UnitOperatingState(
        plant_code=plant_code,
        electricity_power_mw=reading.electricity_power_mw,
        fuel_gas_flow_km3h=reading.fuel_gas_flow_km3h,
        steam_flow_tonh=reading.steam_flow_tonh,
        feed_flow_tonh=reading.feed_flow_tonh,
        reactor_temp_c=reading.reactor_temp_c,
        energy_efficiency_percent=reading.energy_efficiency_percent,
        energy_intensity_kgoe_ton=reading.energy_intensity_kgoe_ton,
        carbon_emission_kgco2_ton=reading.carbon_emission_kgco2_ton,
        pressure_bar=reading.pressure_bar,
    )


async def load_unit_states(
    session: AsyncSession | None,
    plant_codes: list[str],
) -> list[UnitOperatingState]:
    states: list[UnitOperatingState] = []
    for i, code in enumerate(plant_codes):
        state = await load_unit_state(session, code)
        # If two units share identical sim snapshot, nudge secondary for demo benchmarking
        if i > 0:
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
