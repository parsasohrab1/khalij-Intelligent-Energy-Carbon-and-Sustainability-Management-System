"""FR-CAR-01 / FR-CAR-03 — Scope 1 & 2 carbon accounting with per-plant IPCC factors."""

from __future__ import annotations

from dataclasses import dataclass

from app.carbon.factors import EmissionFactors, factors_for
from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class CarbonBreakdown:
    scope1_kgco2: float
    scope2_kgco2: float
    carbon_intensity_kgco2_ton: float
    product_ton: float
    factors_version: str
    plant_code: str | None = None

    @property
    def total_kgco2(self) -> float:
        return self.scope1_kgco2 + self.scope2_kgco2


def compute_scopes(
    *,
    fuel_gas_flow_km3h: float,
    steam_flow_tonh: float,
    electricity_power_mw: float,
    feed_flow_tonh: float,
    duration_hours: float = 1.0,
    plant_code: str | None = None,
    factors: EmissionFactors | None = None,
    settings: Settings | None = None,
) -> CarbonBreakdown:
    """
    Scope 1: fuel gas + steam generation combustion.
    Scope 2: purchased electricity.

    Flow arguments are mean hourly rates over the reporting window;
    multiply by duration_hours for period totals.
    """
    cfg = settings or get_settings()
    ef = factors or (factors_for(plant_code) if plant_code else None)
    if ef is None:
        ef = EmissionFactors(
            plant_code=plant_code or "default",
            natural_gas_kgco2_per_m3=cfg.ef_natural_gas_kgco2_per_m3,
            steam_kgco2_per_ton=cfg.ef_steam_kgco2_per_ton,
            electricity_kgco2_per_kwh=cfg.ef_electricity_kgco2_per_kwh,
            version="settings-fallback",
            source="app settings",
        )

    fuel_m3 = fuel_gas_flow_km3h * 1000.0 * duration_hours
    steam_ton = steam_flow_tonh * duration_hours
    electricity_kwh = electricity_power_mw * 1000.0 * duration_hours
    product_ton = max(feed_flow_tonh * duration_hours, 1e-6)

    scope1 = fuel_m3 * ef.natural_gas_kgco2_per_m3 + steam_ton * ef.steam_kgco2_per_ton
    scope2 = electricity_kwh * ef.electricity_kgco2_per_kwh
    intensity = (scope1 + scope2) / product_ton

    return CarbonBreakdown(
        scope1_kgco2=round(scope1, 2),
        scope2_kgco2=round(scope2, 2),
        carbon_intensity_kgco2_ton=round(intensity, 2),
        product_ton=round(product_ton, 3),
        factors_version=ef.version,
        plant_code=plant_code or ef.plant_code,
    )


def compute_scopes_from_integrals(
    *,
    fuel_gas_km3: float,
    steam_ton: float,
    electricity_mwh: float,
    product_ton: float,
    plant_code: str,
) -> CarbonBreakdown:
    """Compute scopes from already-integrated period totals (not rates)."""
    ef = factors_for(plant_code)
    fuel_m3 = fuel_gas_km3 * 1000.0
    electricity_kwh = electricity_mwh * 1000.0
    product = max(product_ton, 1e-6)

    scope1 = fuel_m3 * ef.natural_gas_kgco2_per_m3 + steam_ton * ef.steam_kgco2_per_ton
    scope2 = electricity_kwh * ef.electricity_kgco2_per_kwh
    intensity = (scope1 + scope2) / product

    return CarbonBreakdown(
        scope1_kgco2=round(scope1, 2),
        scope2_kgco2=round(scope2, 2),
        carbon_intensity_kgco2_ton=round(intensity, 2),
        product_ton=round(product, 3),
        factors_version=ef.version,
        plant_code=plant_code,
    )
