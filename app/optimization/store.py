"""Persist optimization recommendations and operator feedback."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OptimizationRecommendation, RecommendationFeedback
from app.optimization.engine import SetpointAdvice
from app.optimization.simulate import AdviceSimulation


async def persist_recommendations(
    session: AsyncSession,
    advice_items: list[SetpointAdvice],
    simulations: dict[str, AdviceSimulation] | None = None,
) -> list[OptimizationRecommendation]:
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

    now = datetime.now(timezone.utc)
    rec.status = decision
    rec.resolved_at = now
    feedback = RecommendationFeedback(
        recommendation_id=recommendation_id,
        decision=decision,
        operator=operator,
        comment=comment,
        created_at=now,
    )
    session.add(feedback)
    await session.commit()
    await session.refresh(rec)
    await session.refresh(feedback)
    return rec, feedback
