"""
IP Reputation System.
Tracks cumulative anomaly signal per IP using an exponentially
weighted moving average (EWMA). Tags IPs as trusted/suspicious/blocked.

Why EWMA?
  - Recent events matter more than ancient history
  - Naturally decays, so a one-time false positive doesn't permanently stain an IP
  - Cheap to compute incrementally (no full history scan)
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from app.models.database import async_session
from app.models.orm import IPReputation
from config.settings import settings

logger = logging.getLogger("soc.reputation")

# EWMA decay factor: 0.1 means the latest score has 10% weight,
# and the historical average retains 90%. Tune as needed.
EWMA_ALPHA = 0.1

# tag thresholds (applied to reputation_score)
TAG_BLOCKED = 0.25
TAG_SUSPICIOUS = 0.45


def _compute_tag(rep_score: float) -> str:
    if rep_score <= TAG_BLOCKED:
        return "blocked"
    elif rep_score <= TAG_SUSPICIOUS:
        return "suspicious"
    return "trusted"


async def update_reputation(
    ip: str,
    anomaly_score: float,
    attack_type: Optional[str] = None,
):
    """
    Update the IP's reputation after a new event.
    Called from the Kafka consumer pipeline for every scored event.
    """
    # invert anomaly score: high anomaly -> low reputation contribution
    contribution = 1.0 - anomaly_score

    async with async_session() as session:
        result = await session.execute(
            select(IPReputation).where(IPReputation.ip == ip)
        )
        record = result.scalar_one_or_none()

        if record is None:
            # first time seeing this IP
            record = IPReputation(
                ip=ip,
                total_events=1,
                total_alerts=1 if anomaly_score >= settings.anomaly_threshold else 0,
                anomaly_sum=anomaly_score,
                reputation_score=contribution,
                tag=_compute_tag(contribution),
                first_seen=datetime.now(timezone.utc).replace(tzinfo=None),
                last_seen=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            session.add(record)
        else:
            # EWMA update
            record.reputation_score = (
                EWMA_ALPHA * contribution
                + (1 - EWMA_ALPHA) * record.reputation_score
            )
            record.total_events += 1
            record.anomaly_sum += anomaly_score
            if anomaly_score >= settings.anomaly_threshold:
                record.total_alerts += 1
            record.last_seen = datetime.now(timezone.utc).replace(tzinfo=None)
            record.tag = _compute_tag(record.reputation_score)

        await session.commit()

    if anomaly_score >= settings.anomaly_threshold:
        logger.info(
            "IP %s reputation updated: score=%.3f tag=%s (anomaly=%.3f)",
            ip, record.reputation_score, record.tag, anomaly_score,
        )


async def get_reputation(ip: str) -> Optional[IPReputation]:
    """Look up an IP's reputation record."""
    async with async_session() as session:
        result = await session.execute(
            select(IPReputation).where(IPReputation.ip == ip)
        )
        return result.scalar_one_or_none()


async def override_tag(ip: str, tag: str) -> bool:
    """Manually override an IP's tag (analyst action)."""
    async with async_session() as session:
        result = await session.execute(
            select(IPReputation).where(IPReputation.ip == ip)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return False
        record.tag = tag
        await session.commit()
        logger.info("IP %s tag manually set to '%s'", ip, tag)
        return True
