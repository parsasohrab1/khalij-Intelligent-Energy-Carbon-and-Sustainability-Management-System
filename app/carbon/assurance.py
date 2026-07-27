"""E10 — assurance workflow for carbon reports (draft → review → approved → locked)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CarbonReport, CarbonReportAssuranceEvent, Plant


class AssuranceError(RuntimeError):
    """Invalid assurance transition."""


async def ensure_e10_schema(session: AsyncSession) -> None:
    stmts = [
        "ALTER TABLE carbon_reports ADD COLUMN IF NOT EXISTS scope3_kgco2 DOUBLE PRECISION",
        "ALTER TABLE carbon_reports ADD COLUMN IF NOT EXISTS scope3_detail_json TEXT",
        "ALTER TABLE carbon_reports ADD COLUMN IF NOT EXISTS assurance_status VARCHAR(32) DEFAULT 'draft'",
        "ALTER TABLE carbon_reports ADD COLUMN IF NOT EXISTS submitted_by TEXT",
        "ALTER TABLE carbon_reports ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ",
        "ALTER TABLE carbon_reports ADD COLUMN IF NOT EXISTS approved_by TEXT",
        "ALTER TABLE carbon_reports ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ",
        "ALTER TABLE carbon_reports ADD COLUMN IF NOT EXISTS locked_by TEXT",
        "ALTER TABLE carbon_reports ADD COLUMN IF NOT EXISTS locked_at TIMESTAMPTZ",
        "ALTER TABLE carbon_market_syncs ADD COLUMN IF NOT EXISTS external_ref TEXT",
        """
        CREATE TABLE IF NOT EXISTS carbon_report_assurance_events (
            id                  SERIAL PRIMARY KEY,
            report_id           INTEGER NOT NULL REFERENCES carbon_reports(id),
            event_type          TEXT NOT NULL,
            actor               TEXT NOT NULL,
            detail_json         TEXT NOT NULL DEFAULT '{}',
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    ]
    for stmt in stmts:
        try:
            await session.execute(text(stmt))
        except Exception:
            await session.rollback()
            return
    await session.commit()


async def append_assurance_event(
    session: AsyncSession,
    *,
    report_id: int,
    event_type: str,
    actor: str,
    detail: dict[str, Any] | None = None,
    commit: bool = True,
) -> CarbonReportAssuranceEvent:
    row = CarbonReportAssuranceEvent(
        report_id=report_id,
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


async def get_report(
    session: AsyncSession, report_id: int
) -> tuple[CarbonReport, str] | None:
    result = await session.execute(
        select(CarbonReport, Plant.code)
        .join(Plant, Plant.id == CarbonReport.plant_id)
        .where(CarbonReport.id == report_id)
    )
    row = result.first()
    if row is None:
        return None
    return row[0], row[1]


async def submit_report(
    session: AsyncSession, *, report_id: int, actor: str, comment: str | None = None
) -> CarbonReport:
    found = await get_report(session, report_id)
    if found is None:
        raise KeyError(f"Report {report_id} not found")
    report, _ = found
    status = getattr(report, "assurance_status", None) or "draft"
    if status not in {"draft", "in_review"}:
        raise AssuranceError(f"Submit requires draft/in_review (current={status})")
    now = datetime.now(timezone.utc)
    report.assurance_status = "in_review"
    report.submitted_by = actor
    report.submitted_at = now
    await append_assurance_event(
        session,
        report_id=report_id,
        event_type="submitted",
        actor=actor,
        detail={"comment": comment},
        commit=False,
    )
    await session.commit()
    await session.refresh(report)
    return report


async def approve_report(
    session: AsyncSession, *, report_id: int, actor: str, comment: str | None = None
) -> CarbonReport:
    found = await get_report(session, report_id)
    if found is None:
        raise KeyError(f"Report {report_id} not found")
    report, _ = found
    if (report.assurance_status or "draft") != "in_review":
        raise AssuranceError(
            f"Approve requires in_review (current={report.assurance_status})"
        )
    now = datetime.now(timezone.utc)
    report.assurance_status = "approved"
    report.approved_by = actor
    report.approved_at = now
    await append_assurance_event(
        session,
        report_id=report_id,
        event_type="approved",
        actor=actor,
        detail={"comment": comment},
        commit=False,
    )
    await session.commit()
    await session.refresh(report)
    return report


async def lock_report(
    session: AsyncSession, *, report_id: int, actor: str, comment: str | None = None
) -> CarbonReport:
    found = await get_report(session, report_id)
    if found is None:
        raise KeyError(f"Report {report_id} not found")
    report, _ = found
    if (report.assurance_status or "draft") != "approved":
        raise AssuranceError(
            f"Lock requires approved (current={report.assurance_status})"
        )
    now = datetime.now(timezone.utc)
    report.assurance_status = "locked"
    report.locked_by = actor
    report.locked_at = now
    await append_assurance_event(
        session,
        report_id=report_id,
        event_type="locked",
        actor=actor,
        detail={"comment": comment},
        commit=False,
    )
    await session.commit()
    await session.refresh(report)
    return report


async def list_assurance_events(
    session: AsyncSession, report_id: int, *, limit: int = 100
) -> list[CarbonReportAssuranceEvent]:
    stmt = (
        select(CarbonReportAssuranceEvent)
        .where(CarbonReportAssuranceEvent.report_id == report_id)
        .order_by(CarbonReportAssuranceEvent.created_at.asc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())
