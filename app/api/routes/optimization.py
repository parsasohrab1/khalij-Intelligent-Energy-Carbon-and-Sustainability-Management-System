"""FR-OPT-01 / FR-OPT-02 / E9 — optimization, simulation, approve, apply, impact."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_action
from app.core.config import get_settings
from app.db.session import get_db
from app.optimization.apply import (
    ActionWorkflowError,
    apply_recommendation,
    approve_recommendation,
    measure_impact,
)
from app.optimization.engine import advice_to_text, build_structured_advice, classify_units
from app.optimization.simulate import simulate_advice
from app.optimization.snapshots import load_unit_states
from app.optimization.store import (
    get_recommendation,
    list_audit_events,
    list_recommendations,
    persist_recommendations,
    submit_feedback,
)
from app.schemas import (
    AdviceSimulationOut,
    ApplyOut,
    ApplyRequest,
    ApproveRequest,
    AuditEventOut,
    FeedbackOut,
    FeedbackRequest,
    ImpactOut,
    OptimizationRequest,
    OptimizationResponse,
    SetpointAdviceOut,
    UnitEfficiencyOut,
)
from app.services.auth import CurrentUser

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


def _row_to_advice(r) -> SetpointAdviceOut:
    return SetpointAdviceOut(
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
        apply_mode=getattr(r, "apply_mode", None),
        realized_saving_kwh_per_h=getattr(r, "realized_saving_kwh_per_h", None),
        approved_by=getattr(r, "approved_by", None),
        applied_by=getattr(r, "applied_by", None),
    )


@router.post("/analyze", response_model=OptimizationResponse)
async def analyze(
    body: OptimizationRequest,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_action("operate")),
) -> OptimizationResponse:
    states = await load_unit_states(db, body.plant_codes)
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
        if not rows and get_settings().allow_demo_memory():
            from app.demo.memory_recs import memory_recs

            rows = memory_recs.persist(advice_items, simulations)

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
    rows = []
    try:
        rows = await list_recommendations(
            db, plant_code=plant_code, status=status_filter, limit=limit
        )
    except Exception:  # noqa: BLE001
        rows = []
    if not rows and get_settings().allow_demo_memory():
        from app.demo.memory_recs import memory_recs

        rows = memory_recs.list(plant_code=plant_code, status=status_filter, limit=limit)
    return [_row_to_advice(r) for r in rows]


@router.post("/recommendations/{recommendation_id}/simulate", response_model=AdviceSimulationOut)
async def simulate_recommendation(
    recommendation_id: int,
    model: str = Query(default="elm", pattern="^(elm|lstm)$"),
    db: AsyncSession = Depends(get_db),
) -> AdviceSimulationOut:
    from app.demo.memory_recs import memory_recs

    rec = None
    if memory_recs.is_memory_id(recommendation_id):
        rec = memory_recs.get(recommendation_id)
    else:
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
    if memory_recs.is_memory_id(recommendation_id):
        rec.simulated_intensity_delta = sim.intensity_delta
        rec.simulated_efficiency_delta_pp = sim.efficiency_delta_pp
    else:
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
    from datetime import datetime, timezone

    from app.demo.memory_recs import memory_recs

    if memory_recs.is_memory_id(recommendation_id):
        rec = memory_recs.get(recommendation_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        if body.decision not in {"accepted", "rejected"}:
            raise HTTPException(status_code=400, detail="decision must be accepted or rejected")
        if rec.status not in {"pending", "accepted"}:
            raise HTTPException(
                status_code=400, detail=f"Cannot {body.decision} in status={rec.status}"
            )
        now = datetime.now(timezone.utc)
        memory_recs.set_status(
            recommendation_id,
            body.decision,
            actor=body.operator,
            comment=body.comment,
            resolved_at=now if body.decision == "rejected" else None,
        )
        return FeedbackOut(
            recommendation_id=recommendation_id,
            decision=body.decision,
            operator=body.operator,
            comment=body.comment,
            status=body.decision,
            created_at=now,
        )
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


@router.post("/recommendations/{recommendation_id}/approve", response_model=SetpointAdviceOut)
async def approve(
    recommendation_id: int,
    body: ApproveRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_action("operate")),
) -> SetpointAdviceOut:
    from datetime import datetime, timezone

    from app.demo.memory_recs import memory_recs

    if memory_recs.is_memory_id(recommendation_id):
        rec = memory_recs.get(recommendation_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        if rec.status != "accepted":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Approve requires status=accepted (current={rec.status})",
            )
        memory_recs.set_status(
            recommendation_id,
            "approved",
            actor=user.username,
            comment=(body.comment if body else None),
            approved_by=user.username,
            approved_at=datetime.now(timezone.utc),
        )
        updated = memory_recs.get(recommendation_id)
        assert updated is not None
        return _row_to_advice(updated)
    try:
        rec = await approve_recommendation(
            db,
            recommendation_id=recommendation_id,
            actor=user.username,
            comment=(body.comment if body else None),
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Recommendation not found") from None
    except ActionWorkflowError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _row_to_advice(rec)


@router.post("/recommendations/{recommendation_id}/apply", response_model=ApplyOut)
async def apply(
    recommendation_id: int,
    body: ApplyRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_action("apply")),
) -> ApplyOut:
    from datetime import datetime, timezone

    from app.demo.memory_recs import memory_recs

    if memory_recs.is_memory_id(recommendation_id):
        rec = memory_recs.get(recommendation_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        if rec.status != "approved":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Apply requires status=approved (current={rec.status})",
            )
        dry_run = True if body is None or body.dry_run is None else bool(body.dry_run)
        planned = [{"field": k, "value": v} for k, v in json.loads(rec.proposed_json).items()]
        memory_recs.set_status(
            recommendation_id,
            "applied",
            actor=user.username,
            apply_mode="dry_run" if dry_run else "write",
            applied_by=user.username,
            applied_at=datetime.now(timezone.utc),
        )
        return ApplyOut(
            recommendation_id=recommendation_id,
            status="applied",
            apply_mode="dry_run" if dry_run else "write",
            dry_run=dry_run,
            planned=planned,
            written=[] if dry_run else planned,
            skipped=[],
            detail="demo memory apply",
            baseline_intensity=None,
            baseline_efficiency=None,
        )
    try:
        outcome = await apply_recommendation(
            db,
            recommendation_id=recommendation_id,
            actor=user.username,
            dry_run=body.dry_run if body else None,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Recommendation not found") from None
    except ActionWorkflowError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ApplyOut(
        recommendation_id=outcome.recommendation_id,
        status=outcome.status,
        apply_mode=outcome.apply_mode,
        dry_run=outcome.dry_run,
        planned=outcome.planned,
        written=outcome.written,
        skipped=outcome.skipped,
        detail=outcome.detail,
        baseline_intensity=outcome.baseline_intensity,
        baseline_efficiency=outcome.baseline_efficiency,
    )


@router.get("/recommendations/{recommendation_id}/impact", response_model=ImpactOut)
async def impact(
    recommendation_id: int,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_action("operate")),
) -> ImpactOut:
    from app.demo.memory_recs import memory_recs
    from app.services.live_reading import resolve_live_reading

    if memory_recs.is_memory_id(recommendation_id):
        rec = memory_recs.get(recommendation_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        live = await resolve_live_reading(db, rec.plant_code)
        est = float(rec.estimated_energy_saving_kwh_per_h or 0)
        memory_recs.set_status(
            recommendation_id,
            rec.status,
            actor=user.username,
            realized_saving_kwh_per_h=est * 0.85,
        )
        return ImpactOut(
            recommendation_id=recommendation_id,
            plant_code=rec.plant_code,
            status=rec.status,
            baseline_intensity=rec.baseline_intensity,
            current_intensity=live.energy_intensity_kgoe_ton,
            baseline_efficiency=rec.baseline_efficiency,
            current_efficiency=live.energy_efficiency_percent,
            estimated_saving_kwh_per_h=est,
            realized_saving_kwh_per_h=est * 0.85,
            window_minutes=15,
            samples=1,
            detail="demo memory impact from live reading",
        )
    try:
        out = await measure_impact(
            db, recommendation_id=recommendation_id, actor=user.username
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Recommendation not found") from None
    except ActionWorkflowError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ImpactOut(
        recommendation_id=out.recommendation_id,
        plant_code=out.plant_code,
        status=out.status,
        baseline_intensity=out.baseline_intensity,
        current_intensity=out.current_intensity,
        baseline_efficiency=out.baseline_efficiency,
        current_efficiency=out.current_efficiency,
        estimated_saving_kwh_per_h=out.estimated_saving_kwh_per_h,
        realized_saving_kwh_per_h=out.realized_saving_kwh_per_h,
        window_minutes=out.window_minutes,
        samples=out.samples,
        detail=out.detail,
    )


@router.get("/recommendations/{recommendation_id}/audit", response_model=list[AuditEventOut])
async def audit(
    recommendation_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[AuditEventOut]:
    from app.demo.memory_recs import memory_recs

    if memory_recs.is_memory_id(recommendation_id):
        rec = memory_recs.get(recommendation_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        events = memory_recs.list_audit(recommendation_id)
        return [
            AuditEventOut(
                id=e.id,
                recommendation_id=e.recommendation_id,
                event_type=e.event_type,
                actor=e.actor,
                detail=json.loads(e.detail_json or "{}"),
                created_at=e.created_at,
            )
            for e in events
        ]
    rec = await get_recommendation(db, recommendation_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    events = await list_audit_events(db, recommendation_id)
    return [
        AuditEventOut(
            id=e.id,
            recommendation_id=e.recommendation_id,
            event_type=e.event_type,
            actor=e.actor,
            detail=json.loads(e.detail_json or "{}"),
            created_at=e.created_at,
        )
        for e in events
    ]
