"""Phase 2 — carbon factors, periods, Scope 1/2 accounting."""

from datetime import datetime, timezone

from app.carbon.factors import factors_for, load_emission_factors
from app.carbon.reports import period_window
from app.services.carbon import compute_scopes, compute_scopes_from_integrals


def test_emission_factors_per_plant():
    factors = load_emission_factors()
    assert "olefin" in factors and "pta" in factors
    assert factors["olefin"].natural_gas_kgco2_per_m3 != factors["pta"].natural_gas_kgco2_per_m3
    assert factors["olefin"].version.startswith("ipcc")


def test_compute_scopes_uses_plant_factors():
    olefin = compute_scopes(
        fuel_gas_flow_km3h=100,
        steam_flow_tonh=30,
        electricity_power_mw=15,
        feed_flow_tonh=100,
        duration_hours=1,
        plant_code="olefin",
    )
    pta = compute_scopes(
        fuel_gas_flow_km3h=100,
        steam_flow_tonh=30,
        electricity_power_mw=15,
        feed_flow_tonh=100,
        duration_hours=1,
        plant_code="pta",
    )
    assert olefin.scope1_kgco2 > 0 and pta.scope1_kgco2 > 0
    assert olefin.scope1_kgco2 != pta.scope1_kgco2
    assert olefin.carbon_intensity_kgco2_ton > 0
    assert olefin.factors_version == factors_for("olefin").version


def test_compute_scopes_from_integrals():
    breakdown = compute_scopes_from_integrals(
        fuel_gas_km3=100.0,
        steam_ton=30.0,
        electricity_mwh=15.0,
        product_ton=100.0,
        plant_code="olefin",
    )
    assert breakdown.total_kgco2 == breakdown.scope1_kgco2 + breakdown.scope2_kgco2
    assert breakdown.product_ton == 100.0


def test_period_window_daily():
    ref = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    window = period_window("daily", reference=ref, completed_only=True)
    assert window.period_type == "daily"
    assert window.start.day == 24
    assert window.end.day == 25
    assert (window.end - window.start).total_seconds() == 86400


def test_period_window_monthly():
    ref = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    window = period_window("monthly", reference=ref, completed_only=True)
    assert window.start.month == 6 and window.start.day == 1
    assert window.end.month == 7 and window.end.day == 1


def test_period_window_current_day_demo():
    ref = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    window = period_window("daily", reference=ref, completed_only=False)
    assert window.start.day == 25
    assert window.end.day == 26
