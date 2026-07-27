"""E12 — Real-Time Optimization: live advisory computed continuously from plant state.

Read-only surface — RTO never writes setpoints directly. `GET /live` recomputes
fresh advice on every call (cheap in-memory heuristic over the already-live
plant reading, same cost as `/optimization/analyze` without persist/simulate)
so it is correct regardless of deployment topology. The `app.rto.scheduler`
background loop separately queues fresh advice into the existing
accept -> approve -> apply recommendation workflow on a slower cadence.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.rto.engine import compute_rto_cycle
from app.rto.state import rto_status
from app.schemas import RTOLiveOut, RTOStatusOut, RTOUnitTargetOut

router = APIRouter(prefix="/rto", tags=["rto"])


@router.get("/status", response_model=RTOStatusOut)
async def rto_status_view() -> RTOStatusOut:
    settings = get_settings()
    return RTOStatusOut(
        enabled=settings.rto_enabled,
        running=rto_status.running,
        cycle_seconds=rto_status.cycle_seconds,
        persist_interval_seconds=rto_status.persist_interval_seconds,
        last_cycle_at=rto_status.last_cycle_at,
        last_persisted_at=rto_status.last_persisted_at,
        last_persisted_count=rto_status.last_persisted_count,
        last_error=rto_status.last_error,
    )


@router.get("/live", response_model=RTOLiveOut)
async def rto_live(
    plant_codes: str = Query(
        default="", description="Comma-separated plant codes; default = all monitored units"
    ),
    db: AsyncSession = Depends(get_db),
) -> RTOLiveOut:
    settings = get_settings()
    codes = [c.strip() for c in plant_codes.split(",") if c.strip()] or settings.unit_code_list
    result = await compute_rto_cycle(db, codes)
    advice_by_plant = {a.plant_code: a for a in result.advice}

    targets = []
    for bench in result.units:
        advice = advice_by_plant.get(bench.plant_code)
        sec_pct = advice.estimated_sec_reduction_pct if advice else 0.0
        saving_kwh = advice.estimated_energy_saving_kwh_per_h if advice else 0.0
        targets.append(
            RTOUnitTargetOut(
                plant_code=bench.plant_code,
                tier=bench.tier,
                energy_efficiency_percent=bench.energy_efficiency_percent,
                energy_intensity_kgoe_ton=bench.energy_intensity_kgoe_ton,
                gap_pp_vs_best=bench.gap_pp_vs_best,
                benchmark_plant=bench.benchmark_plant,
                on_target=advice is None,
                title=advice.title if advice else None,
                current=advice.current if advice else None,
                proposed=advice.proposed if advice else None,
                deltas=advice.deltas if advice else None,
                estimated_sec_reduction_pct=sec_pct,
                estimated_energy_saving_kwh_per_h=saving_kwh,
            )
        )

    cycle_seconds = (
        rto_status.cycle_seconds if rto_status.running else settings.rto_interval_seconds
    )
    return RTOLiveOut(
        computed_at=result.computed_at,
        cycle_seconds=cycle_seconds,
        total_estimated_saving_kwh_per_h=round(
            sum(t.estimated_energy_saving_kwh_per_h for t in targets), 2
        ),
        units=targets,
    )
