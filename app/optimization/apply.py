"""E9 — approve / apply / impact for setpoint recommendations."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import OptimizationRecommendation
from app.ingestion.opcua_write import WriteNotAllowedError, write_setpoints
from app.optimization.snapshots import load_unit_state
from app.optimization.store import append_audit, get_recommendation
from app.repositories import sensors as sensor_repo

logger = logging.getLogger(__name__)


class ActionWorkflowError(RuntimeError):
    """Invalid status transition or missing gate for E9 actions."""


@dataclass
class ApplyOutcome:
    recommendation_id: int
    status: str
    apply_mode: str
    dry_run: bool
    planned: list[dict[str, Any]]
    written: list[dict[str, Any]]
    skipped: list[str]
    detail: str
    baseline_intensity: float | None
    baseline_efficiency: float | None


@dataclass
class ImpactOutcome:
    recommendation_id: int
    plant_code: str
    status: str
    baseline_intensity: float | None
    current_intensity: float | None
    baseline_efficiency: float | None
    current_efficiency: float | None
    estimated_saving_kwh_per_h: float | None
    realized_saving_kwh_per_h: float | None
    window_minutes: int
    samples: int
    detail: str


async def approve_recommendation(
    session: AsyncSession,
    *,
    recommendation_id: int,
    actor: str,
    comment: str | None = None,
) -> OptimizationRecommendation:
    rec = await get_recommendation(session, recommendation_id)
    if rec is None:
        raise KeyError(f"Recommendation {recommendation_id} not found")
    if rec.status != "accepted":
        raise ActionWorkflowError(
            f"Approve requires status=accepted (current={rec.status})"
        )
    now = datetime.now(timezone.utc)
    rec.status = "approved"
    rec.approved_by = actor
    rec.approved_at = now
    await append_audit(
        session,
        recommendation_id=recommendation_id,
        event_type="approved",
        actor=actor,
        detail={"comment": comment},
        commit=False,
    )
    await session.commit()
    await session.refresh(rec)
    return rec


async def apply_recommendation(
    session: AsyncSession,
    *,
    recommendation_id: int,
    actor: str,
    dry_run: bool | None = None,
    settings: Settings | None = None,
) -> ApplyOutcome:
    cfg = settings or get_settings()
    rec = await get_recommendation(session, recommendation_id)
    if rec is None:
        raise KeyError(f"Recommendation {recommendation_id} not found")
    if rec.status != "approved":
        raise ActionWorkflowError(
            f"Apply requires status=approved (current={rec.status})"
        )
    if cfg.opt_require_sim_before_apply and rec.simulated_intensity_delta is None:
        raise ActionWorkflowError(
            "Simulate before apply (OPT_REQUIRE_SIM_BEFORE_APPLY=true)"
        )

    proposed = json.loads(rec.proposed_json)
    do_dry = cfg.opc_write_dry_run_default if dry_run is None else bool(dry_run)

    # Capture baseline from live plant state before write
    baseline_intensity = None
    baseline_efficiency = None
    try:
        state = await load_unit_state(session, rec.plant_code)
        baseline_intensity = state.energy_intensity_kgoe_ton
        baseline_efficiency = state.energy_efficiency_percent
    except Exception:
        logger.exception("Could not load baseline state for %s", rec.plant_code)
        current = json.loads(rec.current_json)
        baseline_intensity = float(current.get("energy_intensity_kgoe_ton") or 0) or None

    try:
        result = await write_setpoints(
            rec.plant_code, proposed, dry_run=do_dry, settings=cfg
        )
    except WriteNotAllowedError as exc:
        rec.status = "failed"
        await append_audit(
            session,
            recommendation_id=recommendation_id,
            event_type="apply_failed",
            actor=actor,
            detail={"error": str(exc), "dry_run": do_dry},
            commit=False,
        )
        await session.commit()
        raise ActionWorkflowError(str(exc)) from exc

    now = datetime.now(timezone.utc)
    mode = "dry_run" if result.dry_run else "live"
    rec.status = "applied"
    rec.applied_by = actor
    rec.applied_at = now
    rec.apply_mode = mode
    rec.baseline_intensity = baseline_intensity
    rec.baseline_efficiency = baseline_efficiency
    rec.resolved_at = now

    planned = [
        {
            "field": p.field,
            "node_id": p.node_id,
            "value": p.engineering_value,
            "raw": p.value,
        }
        for p in result.planned
    ]
    await append_audit(
        session,
        recommendation_id=recommendation_id,
        event_type="applied",
        actor=actor,
        detail={
            "apply_mode": mode,
            "dry_run": result.dry_run,
            "planned": planned,
            "written": result.written,
            "skipped": result.skipped,
            "detail": result.detail,
            "baseline_intensity": baseline_intensity,
            "baseline_efficiency": baseline_efficiency,
        },
        commit=False,
    )
    await session.commit()
    await session.refresh(rec)

    return ApplyOutcome(
        recommendation_id=rec.id,
        status=rec.status,
        apply_mode=mode,
        dry_run=result.dry_run,
        planned=planned,
        written=result.written,
        skipped=result.skipped,
        detail=result.detail,
        baseline_intensity=baseline_intensity,
        baseline_efficiency=baseline_efficiency,
    )


async def measure_impact(
    session: AsyncSession,
    *,
    recommendation_id: int,
    actor: str = "system",
    settings: Settings | None = None,
) -> ImpactOutcome:
    cfg = settings or get_settings()
    rec = await get_recommendation(session, recommendation_id)
    if rec is None:
        raise KeyError(f"Recommendation {recommendation_id} not found")
    if rec.status not in {"applied", "approved", "accepted"}:
        raise ActionWorkflowError(
            f"Impact tracking expects accepted/approved/applied (current={rec.status})"
        )

    minutes = cfg.opt_impact_window_minutes
    history = await sensor_repo.get_history(
        session, rec.plant_code, minutes=minutes, limit=max(60, minutes * 60)
    )
    intensities = [
        float(r.energy_intensity_kgoe_ton)
        for r in history
        if r.energy_intensity_kgoe_ton is not None
    ]
    efficiencies = [
        float(r.energy_efficiency_percent)
        for r in history
        if getattr(r, "energy_efficiency_percent", None) is not None
    ]

    baseline_i = rec.baseline_intensity
    baseline_e = rec.baseline_efficiency
    if baseline_i is None:
        current = json.loads(rec.current_json)
        baseline_i = current.get("energy_intensity_kgoe_ton")

    current_i = sum(intensities) / len(intensities) if intensities else None
    current_e = sum(efficiencies) / len(efficiencies) if efficiencies else None

    realized = None
    detail = "insufficient_post_apply_samples"
    if baseline_i is not None and current_i is not None:
        # Approximate kWh/h from intensity drop × feed (ton/h) × kgoe→kWh factor used elsewhere
        proposed = json.loads(rec.proposed_json)
        feed = float(proposed.get("feed_flow_tonh") or 100.0)
        # 1 kgoe ≈ 11.63 kWh (standard); keep consistent with intensity_to_energy if available
        from app.ml.features import intensity_to_energy_kwh

        before_kwh = intensity_to_energy_kwh(float(baseline_i), feed, 60)
        after_kwh = intensity_to_energy_kwh(float(current_i), feed, 60)
        realized = round(before_kwh - after_kwh, 2)
        detail = "realized_from_history"
        rec.realized_saving_kwh_per_h = realized
        await append_audit(
            session,
            recommendation_id=recommendation_id,
            event_type="impact",
            actor=actor,
            detail={
                "baseline_intensity": baseline_i,
                "current_intensity": current_i,
                "realized_saving_kwh_per_h": realized,
                "window_minutes": minutes,
                "samples": len(intensities),
            },
            commit=False,
        )
        await session.commit()
        await session.refresh(rec)
    elif rec.estimated_energy_saving_kwh_per_h is not None and rec.status == "applied":
        # Demo fallback: track estimate until plant samples exist
        realized = float(rec.estimated_energy_saving_kwh_per_h)
        rec.realized_saving_kwh_per_h = realized
        detail = "using_estimate_until_plant_samples"
        await append_audit(
            session,
            recommendation_id=recommendation_id,
            event_type="impact",
            actor=actor,
            detail={"realized_saving_kwh_per_h": realized, "source": "estimate"},
            commit=False,
        )
        await session.commit()

    return ImpactOutcome(
        recommendation_id=rec.id,
        plant_code=rec.plant_code,
        status=rec.status,
        baseline_intensity=baseline_i,
        current_intensity=current_i,
        baseline_efficiency=baseline_e,
        current_efficiency=current_e,
        estimated_saving_kwh_per_h=rec.estimated_energy_saving_kwh_per_h,
        realized_saving_kwh_per_h=realized,
        window_minutes=minutes,
        samples=len(intensities),
        detail=detail,
    )
