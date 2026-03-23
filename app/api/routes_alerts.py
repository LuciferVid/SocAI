"""
Alert API routes.
Listing, resolving, and marking false positives.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_session
from app.models.orm import Alert
from app.models.schemas import AlertOut, AlertResolve

logger = logging.getLogger("soc.api.alerts")
router = APIRouter()


@router.get("/", response_model=list[AlertOut])
async def list_alerts(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    severity: Optional[str] = None,
    resolved: Optional[bool] = None,
    session: AsyncSession = Depends(get_session),
):
    """Paginated alert listing with optional filters."""
    query = select(Alert).order_by(desc(Alert.created_at))

    if severity:
        query = query.where(Alert.severity == severity)
    if resolved is not None:
        query = query.where(Alert.resolved == resolved)

    query = query.offset(skip).limit(limit)
    result = await session.execute(query)
    return result.scalars().all()


@router.get("/stats")
async def alert_stats(
    session: AsyncSession = Depends(get_session),
):
    """Aggregate stats for the dashboard."""
    total = await session.execute(select(func.count(Alert.id)))
    active = await session.execute(
        select(func.count(Alert.id)).where(Alert.resolved == False)
    )
    critical = await session.execute(
        select(func.count(Alert.id)).where(
            Alert.severity == "critical", Alert.resolved == False
        )
    )
    return {
        "total_alerts": total.scalar(),
        "active_alerts": active.scalar(),
        "critical_active": critical.scalar(),
    }


@router.post("/{alert_id}/resolve", response_model=AlertOut)
async def resolve_alert(
    alert_id: UUID,
    body: AlertResolve,
    session: AsyncSession = Depends(get_session),
):
    """Mark an alert as resolved, optionally as a false positive."""
    result = await session.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.resolved = True
    alert.resolved_by = body.resolved_by
    alert.resolved_at = datetime.now(timezone.utc)
    alert.is_false_positive = body.is_false_positive

    # if false positive, also label the source event
    if body.is_false_positive:
        from app.models.orm import Event
        event_result = await session.execute(
            select(Event).where(Event.id == alert.event_id)
        )
        event = event_result.scalar_one_or_none()
        if event:
            event.label = "false_positive"

    await session.commit()
    logger.info("alert %s resolved by %s (fp=%s)", alert_id, body.resolved_by, body.is_false_positive)
    return alert
