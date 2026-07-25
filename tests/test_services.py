"""Unit tests for core SRS services (no external infra required)."""

from app.services.auth import Role, authenticate, role_allows
from app.services.carbon import compute_scopes
from app.services.optimization import UnitSnapshot, build_recommendations, classify_units
from app.services.physics import enrich_reading
from app.services.prediction import predict_energy, simulate_what_if
from app.services.vsg import generate_virtual_samples


def test_enrich_reading_ranges():
    out = enrich_reading(
        electricity_power_mw=15,
        fuel_gas_flow_km3h=100,
        steam_flow_tonh=30,
        feed_flow_tonh=100,
        reactor_temp_c=400,
    )
    assert 500 <= out["energy_intensity_kgoe_ton"] <= 800
    assert 20 <= out["carbon_emission_kgco2_ton"] <= 80
    assert 60 <= out["energy_efficiency_percent"] <= 92


def test_carbon_scopes_positive():
    scopes = compute_scopes(
        fuel_gas_flow_km3h=100,
        steam_flow_tonh=30,
        electricity_power_mw=15,
        feed_flow_tonh=100,
        duration_hours=1,
    )
    assert scopes.scope1_kgco2 > 0
    assert scopes.scope2_kgco2 > 0
    assert scopes.total_kgco2 == scopes.scope1_kgco2 + scopes.scope2_kgco2


def test_predict_under_3_seconds():
    result = predict_energy(horizon_minutes=60, model="elm")
    assert result.latency_ms < 3000
    assert result.predicted_energy_kwh > 0
    assert result.mape_estimate <= 5.0


def test_what_if_simulation():
    sim = simulate_what_if(
        reactor_temp_c=410,
        feed_flow_tonh=110,
        fuel_gas_flow_km3h=90,
    )
    assert "estimated_energy_intensity_kgoe_ton" in sim


def test_vsg_monte_carlo():
    samples = generate_virtual_samples(method="mc", n_samples=20, seed=1)
    assert len(samples) == 20
    assert "energy_intensity_kgoe_ton" in samples[0]


def test_vsg_pso():
    samples = generate_virtual_samples(method="pso", n_samples=15, seed=1)
    assert len(samples) == 15


def test_optimization_recommendations():
    units = [
        UnitSnapshot("olefin", 80.0, 620.0),
        UnitSnapshot("pta", 70.0, 700.0),
    ]
    classified = classify_units(units)
    recs = build_recommendations(classified)
    assert any(u["tier"] == "low" for u in classified)
    assert len(recs) >= 1


def test_auth_rbac_and_2fa():
    from app.security.totp import totp
    from app.services.auth import DEMO_TOTP_SECRET, verify_settings_2fa

    # Default login does not force TOTP (AUTH_LOGIN_REQUIRE_2FA=false)
    soft = authenticate("admin", "admin")
    assert soft.ok and soft.token and soft.requires_2fa

    denied = authenticate("admin", "admin", require_2fa=True)
    assert not denied.ok and denied.requires_2fa

    code = totp(DEMO_TOTP_SECRET)
    ok = authenticate("admin", "admin", totp_code=code, require_2fa=True)
    assert ok.ok and ok.token
    assert verify_settings_2fa("admin", code)
    assert not verify_settings_2fa("admin", "000000")
    assert role_allows(Role.ADMIN, "settings")
    assert not role_allows(Role.VIEWER, "settings")
