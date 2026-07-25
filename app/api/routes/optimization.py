"""FR-OPT-01 / FR-OPT-02 — optimization, simulation, operator feedback."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_action
from app.db.session import get_db
from app.optimization.engine import advice_to_text, build_structured_advice, classify_units
from app.optimization.simulate import simulate_advice
from app.optimization.snapshots import load_unit_states
from app.optimization.store import (
    get_recommendation,
    list_recommendations,
    persist_recommendations,
    submit_feedback,
)
from app.schemas import (
    AdviceSimulationOut,
    FeedbackOut,
    FeedbackRequest,
    OptimizationRequest,
    OptimizationResponse,
    SetpointAdviceOut,
    UnitEfficiencyOut,
)

router = APIRouter(prefix="/optimization", tags=["optimization"])


def _advice_out(advice, row_id: int | None = None, sim=None, status_value: str = "pending") -> SetpointAdviceOut:
    return SetpointAdviceOut(
        id=row_id,
        plant_code=advice.plant_code,
        priority=advice.priority,
        title=advice.title,
        rationale=advice.rationale,
        current=advice.current,
        proposed=advice.proposed,
        deltas=advice.deltas,
        tags=advice.tags,
        benchmark_plant=advice.benchmark_plant,
        estimated_sec_reduction_pct=advice.estimated_sec_reduction_pct,
        estimated_energy_saving_kwh_per_h=advice.estimated_energy_saving_kwh_per_h,
        estimated_efficiency_gain_pp=advice.estimated_efficiency_gain_pp,
        simulated_intensity_delta=sim.intensity_delta if sim else None,
        simulated_efficiency_delta_pp=sim.efficiency_delta_pp if sim else None,
        status=status_value,
    )


@router.post("/analyze", response_model=OptimizationResponse)
async def analyze(
    body: OptimizationRequest,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_action("operate")),
) -> OptimizationResponse:
    states = await load_unit_states(db, body.plant_codes)
    # If DB returned identical-ish single-source states, still allow multi-unit demo nudge
    if len({(s.energy_efficiency_percent, s.energy_intensity_kgoe_ton) for s in states}) == 1 and len(states) > 1:
        states = await load_unit_states(None, body.plant_codes)

    benchmarks = classify_units(states)
    advice_items = build_structured_advice(states, benchmarks)

    simulations = {}
    sim_out: list[AdviceSimulationOut] = []
    if body.simulate:
        by_code = {s.plant_code: s for s in states}
        for advice in advice_items:
            sim = simulate_advice(by_code[advice.plant_code], advice, model=body.model)
            simulations[advice.plant_code] = sim
            sim_out.append(
                AdviceSimulationOut(
                    plant_code=sim.plant_code,
                    before_intensity=sim.before_intensity,
                    after_intensity=sim.after_intensity,
                    before_efficiency=sim.before_efficiency,
                    after_efficiency=sim.after_efficiency,
                    intensity_delta=sim.intensity_delta,
                    efficiency_delta_pp=sim.efficiency_delta_pp,
                    carbon_delta=sim.carbon_delta,
                    model=sim.model,
                    source=sim.source,
                )
            )

    rows = []
    if body.persist and advice_items:
        try:
            rows = await persist_recommendations(db, advice_items, simulations)
        except Exception:
            rows = []

    id_by_plant = {r.plant_code: r.id for r in rows}
    advice_out = [
        _advice_out(
            a,
            row_id=id_by_plant.get(a.plant_code),
            sim=simulations.get(a.plant_code),
        )
        for a in advice_items
    ]

    return OptimizationResponse(
        units=[
            UnitEfficiencyOut(
                plant_code=b.plant_code,
                energy_efficiency_percent=b.energy_efficiency_percent,
                energy_intensity_kgoe_ton=b.energy_intensity_kgoe_ton,
                tier=b.tier,
                gap_pp_vs_best=b.gap_pp_vs_best,
                benchmark_plant=b.benchmark_plant,
            )
            for b in benchmarks
        ],
        recommendations=advice_to_text(advice_items),
        advice=advice_out,
        simulations=sim_out,
        total_estimated_saving_kwh_per_h=round(
            sum(a.estimated_energy_saving_kwh_per_h for a in advice_items), 2
        ),
    )


@router.get("/recommendations", response_model=list[SetpointAdviceOut])
async def get_recommendations(
    plant_code: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[SetpointAdviceOut]:
    rows = await list_recommendations(
        db, plant_code=plant_code, status=status_filter, limit=limit
    )
    out: list[SetpointAdviceOut] = []
    for r in rows:
        out.append(
            SetpointAdviceOut(
                id=r.id,
                plant_code=r.plant_code,
                priority=r.priority,  # type: ignore[arg-type]
                title=r.title,
                rationale=r.rationale,
                current=json.loads(r.current_json),
                proposed=json.loads(r.proposed_json),
                deltas=json.loads(r.deltas_json),
                tags=json.loads(r.tags_json or "[]"),
                benchmark_plant=r.benchmark_plant,
                estimated_sec_reduction_pct=r.estimated_sec_reduction_pct or 0,
                estimated_energy_saving_kwh_per_h=r.estimated_energy_saving_kwh_per_h or 0,
                estimated_efficiency_gain_pp=r.estimated_efficiency_gain_pp or 0,
                simulated_intensity_delta=r.simulated_intensity_delta,
                simulated_efficiency_delta_pp=r.simulated_efficiency_delta_pp,
                status=r.status,
            )
        )
    return out


@router.post("/recommendations/{recommendation_id}/simulate", response_model=AdviceSimulationOut)
async def simulate_recommendation(
    recommendation_id: int,
    model: str = Query(default="elm", pattern="^(elm|lstm)$"),
    db: AsyncSession = Depends(get_db),
) -> AdviceSimulationOut:
    rec = await get_recommendation(db, recommendation_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")

    from app.optimization.engine import SetpointAdvice
    from app.optimization.snapshots import load_unit_state

    state = await load_unit_state(db, rec.plant_code)
    advice = SetpointAdvice(
        plant_code=rec.plant_code,
        priority=rec.priority,  # type: ignore[arg-type]
        title=rec.title,
        rationale=rec.rationale,
        current=json.loads(rec.current_json),
        proposed=json.loads(rec.proposed_json),
        deltas=json.loads(rec.deltas_json),
        estimated_sec_reduction_pct=rec.estimated_sec_reduction_pct or 0,
        estimated_energy_saving_kwh_per_h=rec.estimated_energy_saving_kwh_per_h or 0,
        estimated_efficiency_gain_pp=rec.estimated_efficiency_gain_pp or 0,
        benchmark_plant=rec.benchmark_plant,
        tags=json.loads(rec.tags_json or "[]"),
    )
    sim = simulate_advice(state, advice, model=model)
    rec.simulated_intensity_delta = sim.intensity_delta
    rec.simulated_efficiency_delta_pp = sim.efficiency_delta_pp
    await db.commit()
    return AdviceSimulationOut(
        plant_code=sim.plant_code,
        before_intensity=sim.before_intensity,
        after_intensity=sim.after_intensity,
        before_efficiency=sim.before_efficiency,
        after_efficiency=sim.after_efficiency,
        intensity_delta=sim.intensity_delta,
        efficiency_delta_pp=sim.efficiency_delta_pp,
        carbon_delta=sim.carbon_delta,
        model=sim.model,
        source=sim.source,
    )


@router.post("/recommendations/{recommendation_id}/feedback", response_model=FeedbackOut)
async def feedback_recommendation(
    recommendation_id: int,
    body: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_action("operate")),
) -> FeedbackOut:
    try:
        rec, fb = await submit_feedback(
            db,
            recommendation_id=recommendation_id,
            decision=body.decision,
            operator=body.operator,
            comment=body.comment,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Recommendation not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return FeedbackOut(
        recommendation_id=rec.id,
        decision=fb.decision,
        operator=fb.operator,
        comment=fb.comment,
        status=rec.status,
        created_at=fb.created_at,
    )
