"""In-memory optimization recommendations for Kafka/DB-less demos."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from app.optimization.engine import SetpointAdvice
from app.optimization.simulate import AdviceSimulation

_ID_BASE = 900_000


@dataclass
class MemoryRecommendation:
    id: int
    plant_code: str
    priority: str
    title: str
    rationale: str
    current_json: str
    proposed_json: str
    deltas_json: str
    tags_json: str
    benchmark_plant: str | None
    estimated_sec_reduction_pct: float
    estimated_energy_saving_kwh_per_h: float
    estimated_efficiency_gain_pp: float
    simulated_intensity_delta: float | None = None
    simulated_efficiency_delta_pp: float | None = None
    status: str = "pending"
    apply_mode: str | None = None
    realized_saving_kwh_per_h: float | None = None
    approved_by: str | None = None
    applied_by: str | None = None
    approved_at: datetime | None = None
    applied_at: datetime | None = None
    baseline_intensity: float | None = None
    baseline_efficiency: float | None = None
    resolved_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class MemoryAuditEvent:
    id: int
    recommendation_id: int
    event_type: str
    actor: str
    detail_json: str
    created_at: datetime


class MemoryRecStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._next_id = _ID_BASE
        self._recs: dict[int, MemoryRecommendation] = {}
        self._audit: list[MemoryAuditEvent] = []
        self._audit_id = 1

    def is_memory_id(self, recommendation_id: int) -> bool:
        return recommendation_id >= _ID_BASE

    def persist(
        self,
        advice_items: list[SetpointAdvice],
        simulations: dict[str, AdviceSimulation] | None = None,
    ) -> list[MemoryRecommendation]:
        simulations = simulations or {}
        now = datetime.now(timezone.utc)
        rows: list[MemoryRecommendation] = []
        with self._lock:
            for advice in advice_items:
                sim = simulations.get(advice.plant_code)
                rid = self._next_id
                self._next_id += 1
                row = MemoryRecommendation(
                    id=rid,
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
                self._recs[rid] = row
                self._append_audit_unlocked(
                    rid, "created", "system", {"plant_code": advice.plant_code, "title": advice.title}
                )
                rows.append(row)
        return rows

    def list(
        self,
        *,
        plant_code: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[MemoryRecommendation]:
        with self._lock:
            rows = list(self._recs.values())
        rows.sort(key=lambda r: r.created_at, reverse=True)
        if plant_code:
            rows = [r for r in rows if r.plant_code == plant_code]
        if status:
            rows = [r for r in rows if r.status == status]
        return rows[:limit]

    def get(self, recommendation_id: int) -> MemoryRecommendation | None:
        with self._lock:
            return self._recs.get(recommendation_id)

    def set_status(
        self,
        recommendation_id: int,
        status: str,
        *,
        actor: str,
        comment: str | None = None,
        **extra: Any,
    ) -> MemoryRecommendation:
        with self._lock:
            rec = self._recs.get(recommendation_id)
            if rec is None:
                raise KeyError(recommendation_id)
            rec.status = status
            for key, value in extra.items():
                if hasattr(rec, key):
                    setattr(rec, key, value)
            self._append_audit_unlocked(
                recommendation_id, status, actor, {"comment": comment, **extra}
            )
            return rec

    def list_audit(self, recommendation_id: int, *, limit: int = 100) -> list[MemoryAuditEvent]:
        with self._lock:
            events = [e for e in self._audit if e.recommendation_id == recommendation_id]
        return events[:limit]

    def _append_audit_unlocked(
        self, recommendation_id: int, event_type: str, actor: str, detail: dict[str, Any]
    ) -> None:
        eid = self._audit_id
        self._audit_id += 1
        self._audit.append(
            MemoryAuditEvent(
                id=eid,
                recommendation_id=recommendation_id,
                event_type=event_type,
                actor=actor,
                detail_json=json.dumps(detail),
                created_at=datetime.now(timezone.utc),
            )
        )


memory_recs = MemoryRecStore()
