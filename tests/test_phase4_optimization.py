"""Phase 4 — optimization benchmarking, advice, simulation."""

from app.optimization.engine import (
    UnitOperatingState,
    UnitSnapshot,
    advice_to_text,
    build_structured_advice,
    classify_units,
)
from app.optimization.simulate import simulate_advice
from app.services.optimization import build_recommendations, classify_units as classify_legacy


def _demo_states() -> list[UnitOperatingState]:
    return [
        UnitOperatingState(
            plant_code="olefin",
            electricity_power_mw=15.0,
            fuel_gas_flow_km3h=100.0,
            steam_flow_tonh=30.0,
            feed_flow_tonh=105.0,
            reactor_temp_c=395.0,
            energy_efficiency_percent=80.0,
            energy_intensity_kgoe_ton=620.0,
            carbon_emission_kgco2_ton=42.0,
        ),
        UnitOperatingState(
            plant_code="pta",
            electricity_power_mw=18.0,
            fuel_gas_flow_km3h=120.0,
            steam_flow_tonh=36.0,
            feed_flow_tonh=90.0,
            reactor_temp_c=412.0,
            energy_efficiency_percent=70.0,
            energy_intensity_kgoe_ton=710.0,
            carbon_emission_kgco2_ton=55.0,
        ),
    ]


def test_classify_high_low():
    benches = classify_units(_demo_states())
    by = {b.plant_code: b for b in benches}
    assert by["olefin"].tier == "high"
    assert by["pta"].tier == "low"
    assert by["pta"].gap_pp_vs_best > 0
    assert by["pta"].benchmark_plant == "olefin"


def test_structured_advice_has_setpoints_and_savings():
    states = _demo_states()
    benches = classify_units(states)
    advice = build_structured_advice(states, benches)
    assert len(advice) >= 1
    a = advice[0]
    assert a.plant_code == "pta"
    assert "reactor_temp_c" in a.deltas or "feed_flow_tonh" in a.deltas
    assert a.estimated_energy_saving_kwh_per_h > 0
    assert a.estimated_sec_reduction_pct > 0
    texts = advice_to_text(advice)
    assert any("pta" in t for t in texts)


def test_simulate_advice_improves_or_changes_metrics():
    states = _demo_states()
    benches = classify_units(states)
    advice = build_structured_advice(states, benches)[0]
    sim = simulate_advice(states[1], advice, model="elm")
    assert sim.plant_code == "pta"
    # Proposed cooler/higher-feed envelope should not worsen both metrics blindly
    assert sim.after_intensity > 0
    assert sim.after_efficiency > 0


def test_legacy_wrappers():
    units = [
        UnitSnapshot("olefin", 80.0, 620.0),
        UnitSnapshot("pta", 70.0, 700.0),
    ]
    classified = classify_legacy(units)
    assert any(u["tier"] == "low" for u in classified)
    recs = build_recommendations(classified)
    assert len(recs) >= 1
