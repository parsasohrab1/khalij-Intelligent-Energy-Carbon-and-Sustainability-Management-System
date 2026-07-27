"""In-memory carbon reports for demo when TimescaleDB has no period data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock

from app.carbon.factors import factors_for
from app.carbon.reports import PeriodType, period_window
from app.carbon.scope3 import compute_scope3
from app.demo.memory_store import memory_store
from app.services.carbon import compute_scopes_from_integrals
from app.services.live_reading import resolve_live_reading

_ID_BASE = 800_000


@dataclass
class MemoryCarbonReport:
    id: int
    plant_code: str
    period_type: str
    period_start: datetime
    period_end: datetime
    scope1_kgco2: float
    scope2_kgco2: float
    scope3_kgco2: float
    carbon_intensity_kgco2_ton: float
    product_ton: float
    sample_count: int
    factors_version: str
    assurance_status: str = "draft"
    submitted_by: str | None = None
    approved_by: str | None = None
    locked_by: str | None = None
    scope3_detail_json: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MemoryReportStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._next_id = _ID_BASE
        self._reports: dict[int, MemoryCarbonReport] = {}

    def is_memory_id(self, report_id: int) -> bool:
        return report_id >= _ID_BASE

    def list(
        self,
        *,
        plant_code: str | None = None,
        period_type: str | None = None,
        limit: int = 50,
    ) -> list[MemoryCarbonReport]:
        with self._lock:
            rows = list(self._reports.values())
        rows.sort(key=lambda r: r.created_at, reverse=True)
        if plant_code:
            rows = [r for r in rows if r.plant_code == plant_code]
        if period_type:
            rows = [r for r in rows if r.period_type == period_type]
        return rows[:limit]

    def get(self, report_id: int) -> MemoryCarbonReport | None:
        with self._lock:
            return self._reports.get(report_id)

    def upsert(self, report: MemoryCarbonReport) -> MemoryCarbonReport:
        with self._lock:
            for existing in self._reports.values():
                if (
                    existing.plant_code == report.plant_code
                    and existing.period_type == report.period_type
                    and existing.period_start == report.period_start
                ):
                    if existing.assurance_status == "locked":
                        return existing
                    existing.period_end = report.period_end
                    existing.scope1_kgco2 = report.scope1_kgco2
                    existing.scope2_kgco2 = report.scope2_kgco2
                    existing.scope3_kgco2 = report.scope3_kgco2
                    existing.carbon_intensity_kgco2_ton = report.carbon_intensity_kgco2_ton
                    existing.product_ton = report.product_ton
                    existing.sample_count = report.sample_count
                    existing.factors_version = report.factors_version
                    return existing
            if report.id <= 0:
                report.id = self._next_id
                self._next_id += 1
            self._reports[report.id] = report
            return report

    def set_assurance(
        self,
        report_id: int,
        status: str,
        *,
        actor: str,
    ) -> MemoryCarbonReport:
        with self._lock:
            report = self._reports.get(report_id)
            if report is None:
                raise KeyError(report_id)
            report.assurance_status = status
            if status == "submitted":
                report.submitted_by = actor
            elif status == "approved":
                report.approved_by = actor
            elif status == "locked":
                report.locked_by = actor
            return report


memory_reports = MemoryReportStore()


async def generate_memory_report(
    plant_code: str,
    period_type: PeriodType,
    *,
    completed_only: bool = False,
) -> MemoryCarbonReport | None:
    window = period_window(period_type, completed_only=completed_only)
    history = memory_store.history(plant_code, minutes=max(60, int((window.end - window.start).total_seconds() / 60)))
    if not history:
        # Seed one live point so demo always has a report
        live = await resolve_live_reading(None, plant_code)
        history = [live.as_memory()]

    # Approximate integrals from mean rates × hours
    hours = max((window.end - window.start).total_seconds() / 3600.0, 1.0)
    n = len(history)
    fuel = sum(float(r.fuel_gas_flow_km3h or 0) for r in history) / n * hours
    steam = sum(float(r.steam_flow_tonh or 0) for r in history) / n * hours
    power_mwh = sum(float(r.electricity_power_mw or 0) for r in history) / n * hours
    product = sum(float(r.feed_flow_tonh or 0) for r in history) / n * hours

    breakdown = compute_scopes_from_integrals(
        fuel_gas_km3=fuel,
        steam_ton=steam,
        electricity_mwh=power_mwh,
        product_ton=max(product, 1.0),
        plant_code=plant_code,
    )
    s3 = compute_scope3(
        plant_code=plant_code,
        fuel_gas_km3=fuel,
        product_ton=max(product, 1.0),
    )
    ef = factors_for(plant_code)
    report = MemoryCarbonReport(
        id=0,
        plant_code=plant_code,
        period_type=period_type,
        period_start=window.start,
        period_end=window.end,
        scope1_kgco2=breakdown.scope1_kgco2,
        scope2_kgco2=breakdown.scope2_kgco2,
        scope3_kgco2=s3.total_kgco2,
        carbon_intensity_kgco2_ton=breakdown.carbon_intensity_kgco2_ton,
        product_ton=breakdown.product_ton,
        sample_count=n,
        factors_version=ef.version,
    )
    return memory_reports.upsert(report)
