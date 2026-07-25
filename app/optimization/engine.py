"""Phase 4 — operational optimization (FR-OPT-01 / FR-OPT-02)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Tier = Literal["high", "low"]


@dataclass
class UnitOperatingState:
    plant_code: str
    electricity_power_mw: float
    fuel_gas_flow_km3h: float
    steam_flow_tonh: float
    feed_flow_tonh: float
    reactor_temp_c: float
    energy_efficiency_percent: float
    energy_intensity_kgoe_ton: float
    carbon_emission_kgco2_ton: float | None = None
    pressure_bar: float | None = None


@dataclass
class UnitBenchmark:
    plant_code: str
    energy_efficiency_percent: float
    energy_intensity_kgoe_ton: float
    tier: Tier
    gap_pp_vs_best: float
    benchmark_plant: str | None


@dataclass
class SetpointAdvice:
    """Structured operator advice for key variables (FR-OPT-02)."""

    plant_code: str
    priority: Literal["high", "medium", "low"]
    title: str
    rationale: str
    current: dict[str, float]
    proposed: dict[str, float]
    deltas: dict[str, float]
    estimated_sec_reduction_pct: float
    estimated_energy_saving_kwh_per_h: float
    estimated_efficiency_gain_pp: float
    benchmark_plant: str | None = None
    tags: list[str] = field(default_factory=list)


def classify_units(states: list[UnitOperatingState]) -> list[UnitBenchmark]:
    if not states:
        return []
    median_eff = sorted(s.energy_efficiency_percent for s in states)[len(states) // 2]
    best = max(states, key=lambda s: s.energy_efficiency_percent)
    out: list[UnitBenchmark] = []
    for s in states:
        tier: Tier = "high" if s.energy_efficiency_percent >= median_eff else "low"
        out.append(
            UnitBenchmark(
                plant_code=s.plant_code,
                energy_efficiency_percent=s.energy_efficiency_percent,
                energy_intensity_kgoe_ton=s.energy_intensity_kgoe_ton,
                tier=tier,
                gap_pp_vs_best=round(best.energy_efficiency_percent - s.energy_efficiency_percent, 2),
                benchmark_plant=best.plant_code if s.plant_code != best.plant_code else None,
            )
        )
    return out


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def build_structured_advice(
    states: list[UnitOperatingState],
    benchmarks: list[UnitBenchmark],
) -> list[SetpointAdvice]:
    """
    Produce actionable setpoint recommendations for low-efficiency units.
    Aligns toward the best (high-efficiency) unit operating envelope.
    """
    by_code = {s.plant_code: s for s in states}
    bench_by_code = {b.plant_code: b for b in benchmarks}
    best_code = max(states, key=lambda s: s.energy_efficiency_percent).plant_code
    best = by_code[best_code]
    advice: list[SetpointAdvice] = []

    for state in states:
        bench = bench_by_code[state.plant_code]
        if bench.tier != "low":
            continue

        current = {
            "reactor_temp_c": state.reactor_temp_c,
            "feed_flow_tonh": state.feed_flow_tonh,
            "fuel_gas_flow_km3h": state.fuel_gas_flow_km3h,
            "steam_flow_tonh": state.steam_flow_tonh,
            "electricity_power_mw": state.electricity_power_mw,
        }

        # Move toward best unit: cooler reactor if hotter, higher feed if lower, trim fuel/steam
        temp_delta = 0.0
        if state.reactor_temp_c > best.reactor_temp_c + 1:
            temp_delta = -_clip(state.reactor_temp_c - best.reactor_temp_c, 3.0, 10.0)
        elif state.energy_intensity_kgoe_ton > 650:
            temp_delta = -7.0

        feed_delta = 0.0
        if state.feed_flow_tonh < best.feed_flow_tonh - 1:
            feed_delta = _clip(best.feed_flow_tonh - state.feed_flow_tonh, 2.0, 10.0)
        elif state.energy_intensity_kgoe_ton > 650:
            feed_delta = 5.0

        fuel_delta = 0.0
        if state.fuel_gas_flow_km3h > best.fuel_gas_flow_km3h + 1:
            fuel_delta = -_clip(state.fuel_gas_flow_km3h - best.fuel_gas_flow_km3h, 2.0, 15.0)

        steam_delta = 0.0
        if state.steam_flow_tonh > best.steam_flow_tonh + 0.5:
            steam_delta = -_clip(state.steam_flow_tonh - best.steam_flow_tonh, 1.0, 8.0)

        proposed = {
            "reactor_temp_c": round(_clip(state.reactor_temp_c + temp_delta, 380, 420), 2),
            "feed_flow_tonh": round(_clip(state.feed_flow_tonh + feed_delta, 80, 120), 2),
            "fuel_gas_flow_km3h": round(
                _clip(state.fuel_gas_flow_km3h + fuel_delta, 50, 150), 2
            ),
            "steam_flow_tonh": round(_clip(state.steam_flow_tonh + steam_delta, 10, 50), 2),
            "electricity_power_mw": round(state.electricity_power_mw, 2),
        }
        deltas = {
            k: round(proposed[k] - current[k], 2)
            for k in proposed
            if abs(proposed[k] - current[k]) > 0.05
        }
        if not deltas:
            continue

        # Heuristic savings from intensity gap vs best
        intensity_gap = max(0.0, state.energy_intensity_kgoe_ton - best.energy_intensity_kgoe_ton)
        sec_reduction_pct = min(12.0, intensity_gap / max(state.energy_intensity_kgoe_ton, 1) * 100)
        # kWh/h ≈ intensity * feed * 11.63 * (sec_reduction/100)
        energy_saving = (
            state.energy_intensity_kgoe_ton
            * state.feed_flow_tonh
            * 11.63
            * (sec_reduction_pct / 100.0)
        )
        eff_gain = min(bench.gap_pp_vs_best, 8.0)

        tags = ["sec", "benchmark"]
        if "reactor_temp_c" in deltas:
            tags.append("reactor_temp")
        if "feed_flow_tonh" in deltas:
            tags.append("feed_ratio")
        if "fuel_gas_flow_km3h" in deltas or "steam_flow_tonh" in deltas:
            tags.append("utilities")

        advice.append(
            SetpointAdvice(
                plant_code=state.plant_code,
                priority="high" if bench.gap_pp_vs_best >= 3 else "medium",
                title=f"Align '{state.plant_code}' with high-efficiency '{best_code}'",
                rationale=(
                    f"Unit is low-efficiency ({state.energy_efficiency_percent:.1f}% vs "
                    f"{best.energy_efficiency_percent:.1f}% on {best_code}). "
                    f"Adjust reactor temperature / feed ratio to cut SEC "
                    f"(intensity {state.energy_intensity_kgoe_ton:.1f} → target ~"
                    f"{best.energy_intensity_kgoe_ton:.1f} kgoe/t)."
                ),
                current=current,
                proposed=proposed,
                deltas=deltas,
                estimated_sec_reduction_pct=round(sec_reduction_pct, 2),
                estimated_energy_saving_kwh_per_h=round(energy_saving, 2),
                estimated_efficiency_gain_pp=round(eff_gain, 2),
                benchmark_plant=best_code,
                tags=tags,
            )
        )

    return advice


def advice_to_text(items: list[SetpointAdvice]) -> list[str]:
    lines: list[str] = []
    for a in items:
        delta_txt = ", ".join(f"{k} {v:+.1f}" for k, v in a.deltas.items())
        lines.append(
            f"[{a.plant_code}] {a.title}: {delta_txt}. "
            f"Est. SEC −{a.estimated_sec_reduction_pct:.1f}%, "
            f"~{a.estimated_energy_saving_kwh_per_h:.0f} kWh/h, "
            f"+{a.estimated_efficiency_gain_pp:.1f} pp efficiency."
        )
    if not lines:
        lines.append("All monitored units are within the high-efficiency band.")
    return lines


# Backward-compatible aliases used by older imports
@dataclass
class UnitSnapshot:
    plant_code: str
    energy_efficiency_percent: float
    energy_intensity_kgoe_ton: float


def classify_units_legacy(units: list[UnitSnapshot]) -> list[dict[str, Any]]:
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
        for b in classify_units(states)
    ]


def build_recommendations(classified: list[dict]) -> list[str]:
    """Legacy string recommendations from classified dicts."""
    states = [
        UnitOperatingState(
            plant_code=u["plant_code"],
            electricity_power_mw=15.0,
            fuel_gas_flow_km3h=100.0,
            steam_flow_tonh=30.0,
            feed_flow_tonh=100.0,
            reactor_temp_c=400.0,
            energy_efficiency_percent=u["energy_efficiency_percent"],
            energy_intensity_kgoe_ton=u["energy_intensity_kgoe_ton"],
        )
        for u in classified
    ]
    benchmarks = classify_units(states)
    # Restore tiers from classified input
    for b, u in zip(benchmarks, classified, strict=False):
        b.tier = u.get("tier", b.tier)  # type: ignore[assignment]
    return advice_to_text(build_structured_advice(states, benchmarks))
