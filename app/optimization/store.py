"""Persist optimization recommendations, feedback, and E9 audit events."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    OptimizationRecommendation,
    RecommendationAuditEvent,
    RecommendationFeedback,
)
from app.optimization.engine import SetpointAdvice
from app.optimization.simulate import AdviceSimulation


async def ensure_e9_schema(session: AsyncSession) -> None:
    """Best-effort ADD COLUMN / CREATE for demo volumes without manual migrate."""
    alters = [
        "ALTER TABLE optimization_recommendations ADD COLUMN IF NOT EXISTS approved_by TEXT",
        "ALTER TABLE optimization_recommendations ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ",
        "ALTER TABLE optimization_recommendations ADD COLUMN IF NOT EXISTS applied_by TEXT",
        "ALTER TABLE optimization_recommendations ADD COLUMN IF NOT EXISTS applied_at TIMESTAMPTZ",
        "ALTER TABLE optimization_recommendations ADD COLUMN IF NOT EXISTS apply_mode VARCHAR(16)",
        "ALTER TABLE optimization_recommendations ADD COLUMN IF NOT EXISTS baseline_intensity DOUBLE PRECISION",
        "ALTER TABLE optimization_recommendations ADD COLUMN IF NOT EXISTS baseline_efficiency DOUBLE PRECISION",
        "ALTER TABLE optimization_recommendations ADD COLUMN IF NOT EXISTS realized_saving_kwh_per_h DOUBLE PRECISION",
        """
        CREATE TABLE IF NOT EXISTS recommendation_audit_events (
            id                  SERIAL PRIMARY KEY,
            recommendation_id   INTEGER NOT NULL REFERENCES optimization_recommendations(id),
            event_type          TEXT NOT NULL,
            actor               TEXT NOT NULL,
            detail_json         TEXT NOT NULL DEFAULT '{}',
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    ]
    for stmt in alters:
        try:
            await session.execute(text(stmt))
        except Exception:
            await session.rollback()
            return
    await session.commit()


async def append_audit(
    session: AsyncSession,
    *,
    recommendation_id: int,
    event_type: str,
    actor: str,
    detail: dict[str, Any] | None = None,
    commit: bool = True,
) -> RecommendationAuditEvent:
    row = RecommendationAuditEvent(
        recommendation_id=recommendation_id,
        event_type=event_type,
        actor=actor,
        detail_json=json.dumps(detail or {}),
        created_at=datetime.now(timezone.utc),
    )
    session.add(row)
    if commit:
        await session.commit()
        await session.refresh(row)
    return row


async def persist_recommendations(
    session: AsyncSession,
    advice_items: list[SetpointAdvice],
    simulations: dict[str, AdviceSimulation] | None = None,
) -> list[OptimizationRecommendation]:
    await ensure_e9_schema(session)
    rows: list[OptimizationRecommendation] = []
    simulations = simulations or {}
    now = datetime.now(timezone.utc)
    for advice in advice_items:
        sim = simulations.get(advice.plant_code)
        row = OptimizationRecommendation(
            plant_code=advice.plant_code,
            priority=advice.priority,
            title=advice.title,
            rationale=advice.rationale,
            current_json=json.dumps(advice.current),
            proposed_json=json.dumps(advice.proposed),
            deltas_json=json.dumps(advice.deltas),
            tags_json=json.dumps(advice.tags),
            benchmark_plant=advice.benchmark_plant,
            estimated_sec_reduction_pct=advice.estimated_sec_reduction_pct,
            estimated_energy_saving_kwh_per_h=advice.estimated_energy_saving_kwh_per_h,
            estimated_efficiency_gain_pp=advice.estimated_efficiency_gain_pp,
            simulated_intensity_delta=sim.intensity_delta if sim else None,
            simulated_efficiency_delta_pp=sim.efficiency_delta_pp if sim else None,
            status="pending",
            created_at=now,
        )
        session.add(row)
        rows.append(row)
    await session.commit()
    for row in rows:
        await session.refresh(row)
        await append_audit(
            session,
            recommendation_id=row.id,
            event_type="created",
            actor="system",
            detail={"plant_code": row.plant_code, "title": row.title},
        )
    return rows


async def list_recommendations(
    session: AsyncSession,
    *,
    plant_code: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[OptimizationRecommendation]:
    stmt = (
        select(OptimizationRecommendation)
        .order_by(OptimizationRecommendation.created_at.desc())
        .limit(limit)
    )
    if plant_code:
        stmt = stmt.where(OptimizationRecommendation.plant_code == plant_code)
    if status:
        stmt = stmt.where(OptimizationRecommendation.status == status)
    return list((await session.execute(stmt)).scalars().all())


async def get_recommendation(
    session: AsyncSession, recommendation_id: int
) -> OptimizationRecommendation | None:
    result = await session.execute(
        select(OptimizationRecommendation).where(
            OptimizationRecommendation.id == recommendation_id
        )
    )
    return result.scalar_one_or_none()


async def list_audit_events(
    session: AsyncSession,
    recommendation_id: int,
    *,
    limit: int = 100,
) -> list[RecommendationAuditEvent]:
    stmt = (
        select(RecommendationAuditEvent)
        .where(RecommendationAuditEvent.recommendation_id == recommendation_id)
        .order_by(RecommendationAuditEvent.created_at.asc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def submit_feedback(
    session: AsyncSession,
    *,
    recommendation_id: int,
    decision: str,
    operator: str,
    comment: str | None = None,
) -> tuple[OptimizationRecommendation, RecommendationFeedback]:
    rec = await get_recommendation(session, recommendation_id)
    if rec is None:
        raise KeyError(f"Recommendation {recommendation_id} not found")
    if decision not in {"accepted", "rejected"}:
        raise ValueError("decision must be accepted or rejected")
    if rec.status not in {"pending", "accepted"}:
        raise ValueError(f"Cannot {decision} recommendation in status={rec.status}")

    now = datetime.now(timezone.utc)
    rec.status = decision
    if decision == "rejected":
        rec.resolved_at = now
    feedback = RecommendationFeedback(
        recommendation_id=recommendation_id,
        decision=decision,
        operator=operator,
        comment=comment,
        created_at=now,
    )
    session.add(feedback)
    await append_audit(
        session,
        recommendation_id=recommendation_id,
        event_type=decision,
        actor=operator,
        detail={"comment": comment},
        commit=False,
    )
    await session.commit()
    await session.refresh(rec)
    await session.refresh(feedback)
    return rec, feedback
