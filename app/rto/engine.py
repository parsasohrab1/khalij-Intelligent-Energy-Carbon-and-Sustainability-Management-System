"""FR-RTO-01 — one RTO tick: read live plant state, benchmark, and advise.

Pure re-use of the existing FR-OPT-01/02 heuristic (`app.optimization.engine`) —
RTO's job is *when* advice is (re)computed (continuously, from live data),
not a different optimization model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.optimization.engine import (
    SetpointAdvice,
    UnitBenchmark,
    build_structured_advice,
    classify_units,
)
from app.optimization.snapshots import load_unit_states

RTO_TAG = "rto"


@dataclass
class RTOCycleResult:
    computed_at: datetime
    units: list[UnitBenchmark]
    advice: list[SetpointAdvice]


async def compute_rto_cycle(
    session: AsyncSession | None,
    plant_codes: list[str],
) -> RTOCycleResult:
    states = await load_unit_states(session, plant_codes)
    # Memory-demo quirk: if all units resolved to an identical snapshot, reload
    # unpinned from the session so the per-unit simulator nudge in
    # load_unit_states can differentiate them (mirrors /optimization/analyze).
    distinct = {(s.energy_efficiency_percent, s.energy_intensity_kgoe_ton) for s in states}
    if len(distinct) == 1 and len(states) > 1:
        states = await load_unit_states(None, plant_codes)

    benchmarks = classify_units(states)
    advice = build_structured_advice(states, benchmarks)
    for item in advice:
        if RTO_TAG not in item.tags:
            item.tags.append(RTO_TAG)

    return RTOCycleResult(
        computed_at=datetime.now(timezone.utc),
        units=benchmarks,
        advice=advice,
    )
