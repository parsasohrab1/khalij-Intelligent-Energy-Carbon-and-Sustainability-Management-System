"""Period windows and aggregation for sustainability reports (R-GEN-04)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

PeriodType = Literal["daily", "monthly", "yearly"]


@dataclass(frozen=True)
class PeriodWindow:
    period_type: PeriodType
    period_start: datetime
    period_end: datetime


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def previous_daily_window(as_of: datetime | None = None) -> PeriodWindow:
    now = _ensure_utc(as_of or datetime.now(timezone.utc))
    end = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    start = end - timedelta(days=1)
    return PeriodWindow("daily", start, end)


def previous_monthly_window(as_of: datetime | None = None) -> PeriodWindow:
    now = _ensure_utc(as_of or datetime.now(timezone.utc))
    end = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    if now.month == 1:
        start = datetime(now.year - 1, 12, 1, tzinfo=timezone.utc)
    else:
        start = datetime(now.year, now.month - 1, 1, tzinfo=timezone.utc)
    return PeriodWindow("monthly", start, end)


def previous_yearly_window(as_of: datetime | None = None) -> PeriodWindow:
    now = _ensure_utc(as_of or datetime.now(timezone.utc))
    end = datetime(now.year, 1, 1, tzinfo=timezone.utc)
    start = datetime(now.year - 1, 1, 1, tzinfo=timezone.utc)
    return PeriodWindow("yearly", start, end)


def window_for(
    period_type: PeriodType,
    as_of: datetime | None = None,
    *,
    use_previous: bool = True,
) -> PeriodWindow:
    """
    use_previous=True → completed prior period (scheduler default).
    use_previous=False → current incomplete period to date.
    """
    now = _ensure_utc(as_of or datetime.now(timezone.utc))
    if use_previous:
        if period_type == "daily":
            return previous_daily_window(now)
        if period_type == "monthly":
            return previous_monthly_window(now)
        return previous_yearly_window(now)

    if period_type == "daily":
        start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        return PeriodWindow("daily", start, now)
    if period_type == "monthly":
        start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        return PeriodWindow("monthly", start, now)
    start = datetime(now.year, 1, 1, tzinfo=timezone.utc)
    return PeriodWindow("yearly", start, now)
