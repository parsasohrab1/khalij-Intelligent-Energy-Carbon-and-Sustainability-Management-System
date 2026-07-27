"""Phase 1 / E7 — stream alerts API with severity + operate-gated resolve."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_action
from app.core.config import get_settings
from app.db.session import get_db
from app.ingestion.freshness import check_freshness, list_open_alerts, raise_alert_if_needed, resolve_alert
from app.schemas import StreamAlertOut

router = APIRouter(prefix="/alerts", tags=["alerts"])


def alert_severity(alert_type: str) -> str:
    """Light alarm philosophy for operator console (E7)."""
    mapping = {
        "stream_missing": "critical",
        "data_quality": "warning",
        "stream_stale": "warning",
    }
    return mapping.get(alert_type, "info")


def _to_out(a) -> StreamAlertOut:
    return StreamAlertOut(
        id=a.id,
        plant_code=a.plant_code,
        alert_type=a.alert_type,
        message=a.message,
        age_seconds=a.age_seconds,
        created_at=a.created_at,
        resolved_at=a.resolved_at,
        severity=alert_severity(a.alert_type),  # type: ignore[arg-type]
    )


@router.get("", response_model=list[StreamAlertOut])
async def get_alerts(db: AsyncSession = Depends(get_db)) -> list[StreamAlertOut]:
    settings = get_settings()
    for code in settings.unit_code_list:
        status_obj = await check_freshness(db, code, settings)
        if status_obj.status != "ok":
            await raise_alert_if_needed(db, status_obj, settings)

    alerts = await list_open_alerts(db)
    return [_to_out(a) for a in alerts]


@router.post("/{alert_id}/resolve", response_model=StreamAlertOut)
async def ack_alert(
    alert_id: int,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_action("operate")),
) -> StreamAlertOut:
    alert = await resolve_alert(db, alert_id)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    return _to_out(alert)
