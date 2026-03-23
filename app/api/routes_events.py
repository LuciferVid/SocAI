"""
Event API routes.
Paginated listing, search by IP/time, and label update for feedback loop.
"""

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_session
from app.models.orm import Event
from app.models.schemas import EventOut, EventLabelUpdate

logger = logging.getLogger("soc.api.events")
router = APIRouter()


@router.get("/", response_model=list[EventOut])
async def list_events(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    source_ip: Optional[str] = None,
    min_score: Optional[float] = None,
    attack_type: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """Paginated event listing with optional filters."""
    query = select(Event).order_by(desc(Event.created_at))

    if source_ip:
        query = query.where(Event.source_ip == source_ip)
    if min_score is not None:
        query = query.where(Event.anomaly_score >= min_score)
    if attack_type:
        query = query.where(Event.attack_type == attack_type)

    query = query.offset(skip).limit(limit)
    result = await session.execute(query)
    return result.scalars().all()


@router.get("/count")
async def event_count(
    session: AsyncSession = Depends(get_session),
):
    """Total event count — useful for dashboard stats."""
    result = await session.execute(select(func.count(Event.id)))
    return {"count": result.scalar()}


@router.get("/{event_id}", response_model=EventOut)
async def get_event(
    event_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    """Fetch a single event by ID."""
    result = await session.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.patch("/{event_id}/label")
async def label_event(
    event_id: UUID,
    body: EventLabelUpdate,
    session: AsyncSession = Depends(get_session),
):
    """
    Update an event's label (for the feedback loop).
    Valid labels: normal, attack, false_positive.
    """
    result = await session.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    event.label = body.label
    await session.commit()
    logger.info("event %s labeled as '%s'", event_id, body.label)
    return {"status": "labeled", "event_id": str(event_id), "label": body.label}
