"""Phase 1 — stream stale / missing alerts API."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.ingestion.freshness import check_freshness, list_open_alerts, raise_alert_if_needed, resolve_alert
from app.schemas import StreamAlertOut

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[StreamAlertOut])
async def get_alerts(db: AsyncSession = Depends(get_db)) -> list[StreamAlertOut]:
    settings = get_settings()
    # Evaluate freshness for configured units before listing
    for code in settings.unit_code_list:
        status_obj = await check_freshness(db, code, settings)
        if status_obj.status != "ok":
            await raise_alert_if_needed(db, status_obj, settings)

    alerts = await list_open_alerts(db)
    return [
        StreamAlertOut(
            id=a.id,
            plant_code=a.plant_code,
            alert_type=a.alert_type,
            message=a.message,
            age_seconds=a.age_seconds,
            created_at=a.created_at,
            resolved_at=a.resolved_at,
        )
        for a in alerts
    ]


@router.post("/{alert_id}/resolve", response_model=StreamAlertOut)
async def ack_alert(alert_id: int, db: AsyncSession = Depends(get_db)) -> StreamAlertOut:
    alert = await resolve_alert(db, alert_id)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    return StreamAlertOut(
        id=alert.id,
        plant_code=alert.plant_code,
        alert_type=alert.alert_type,
        message=alert.message,
        age_seconds=alert.age_seconds,
        created_at=alert.created_at,
        resolved_at=alert.resolved_at,
    )
