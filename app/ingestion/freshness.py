"""Stream freshness checks and alert records (Phase 1 + E6 quality)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import StreamAlert
from app.ingestion.quality import quality_is_healthy
from app.repositories import sensors as sensor_repo


class AlertType(str, Enum):
    STREAM_STALE = "stream_stale"
    STREAM_MISSING = "stream_missing"
    DATA_QUALITY = "data_quality"


@dataclass
class FreshnessStatus:
    plant_code: str
    status: str  # ok | stale | missing | bad_quality
    age_seconds: float | None
    threshold_seconds: float
    message: str
    quality: str | None = None
    source: str | None = None


async def check_freshness(
    session: AsyncSession,
    plant_code: str,
    settings: Settings | None = None,
) -> FreshnessStatus:
    cfg = settings or get_settings()
    age = await sensor_repo.reading_age_seconds(session, plant_code)
    threshold = cfg.stale_data_seconds
    quality = None
    source = None
    try:
        latest = await sensor_repo.get_latest_reading(session, plant_code)
        if latest is not None:
            _, reading = latest
            quality = getattr(reading, "quality", None)
            source = getattr(reading, "source", None)
    except Exception:  # noqa: BLE001
        latest = None

    if age is None:
        return FreshnessStatus(
            plant_code=plant_code,
            status="missing",
            age_seconds=None,
            threshold_seconds=threshold,
            message=f"No sensor readings stored for '{plant_code}'",
            quality=quality,
            source=source,
        )
    if age > threshold:
        return FreshnessStatus(
            plant_code=plant_code,
            status="stale",
            age_seconds=round(age, 3),
            threshold_seconds=threshold,
            message=(
                f"Stream stale for '{plant_code}': last sample {age:.1f}s ago "
                f"(threshold {threshold:.1f}s)"
            ),
            quality=quality,
            source=source,
        )
    if quality and not quality_is_healthy(
        quality, allow_uncertain=cfg.opc_ua_allow_uncertain
    ):
        return FreshnessStatus(
            plant_code=plant_code,
            status="bad_quality",
            age_seconds=round(age, 3),
            threshold_seconds=threshold,
            message=f"OPC data quality '{quality}' for '{plant_code}'",
            quality=quality,
            source=source,
        )
    return FreshnessStatus(
        plant_code=plant_code,
        status="ok",
        age_seconds=round(age, 3),
        threshold_seconds=threshold,
        message="Stream healthy",
        quality=quality,
        source=source,
    )


async def raise_alert_if_needed(
    session: AsyncSession,
    status: FreshnessStatus,
    settings: Settings | None = None,
) -> StreamAlert | None:
    if status.status == "ok":
        return None

    cfg = settings or get_settings()
    if status.status == "missing":
        alert_type = AlertType.STREAM_MISSING.value
    elif status.status == "bad_quality":
        alert_type = AlertType.DATA_QUALITY.value
    else:
        alert_type = AlertType.STREAM_STALE.value

    result = await session.execute(
        select(StreamAlert)
        .where(
            StreamAlert.plant_code == status.plant_code,
            StreamAlert.alert_type == alert_type,
            StreamAlert.resolved_at.is_(None),
        )
        .order_by(StreamAlert.created_at.desc())
        .limit(1)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        created = existing.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - created).total_seconds()
        if age < cfg.stream_alert_cooldown_seconds:
            return existing

    alert = StreamAlert(
        plant_code=status.plant_code,
        alert_type=alert_type,
        message=status.message,
        age_seconds=status.age_seconds,
        created_at=datetime.now(timezone.utc),
    )
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    return alert


async def list_open_alerts(session: AsyncSession, limit: int = 50) -> list[StreamAlert]:
    result = await session.execute(
        select(StreamAlert)
        .where(StreamAlert.resolved_at.is_(None))
        .order_by(StreamAlert.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def resolve_alert(session: AsyncSession, alert_id: int) -> StreamAlert | None:
    result = await session.execute(select(StreamAlert).where(StreamAlert.id == alert_id))
    alert = result.scalar_one_or_none()
    if alert is None:
        return None
    alert.resolved_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(alert)
    return alert


def freshness_to_dict(status: FreshnessStatus) -> dict[str, Any]:
    return {
        "plant_code": status.plant_code,
        "status": status.status,
        "age_seconds": status.age_seconds,
        "threshold_seconds": status.threshold_seconds,
        "message": status.message,
        "quality": status.quality,
        "source": status.source,
    }
