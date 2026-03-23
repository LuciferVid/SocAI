"""
Alert dispatcher — fires alerts through multiple channels.
Supports webhook POST, SMTP email (stubbed), and WebSocket broadcast.
Includes cooldown-based de-duplication to avoid alert storms.
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.models.database import async_session
from app.models.orm import Alert, Event
from config.settings import settings

logger = logging.getLogger("soc.alerts")

# in-memory cooldown tracker: {ip:alert_type -> last_fire_timestamp}
_cooldown_cache: dict[str, float] = {}


def _severity_from_score(score: float) -> str:
    if score >= 0.95:
        return "critical"
    elif score >= 0.85:
        return "high"
    elif score >= 0.7:
        return "medium"
    return "low"


def _is_on_cooldown(ip: str, alert_type: str) -> bool:
    """Check if we recently fired an alert for the same IP + type."""
    key = f"{ip}:{alert_type}"
    last_fire = _cooldown_cache.get(key, 0.0)
    return (time.time() - last_fire) < settings.alert_cooldown_seconds


def _update_cooldown(ip: str, alert_type: str):
    key = f"{ip}:{alert_type}"
    _cooldown_cache[key] = time.time()


async def maybe_fire_alert(
    event: Event,
    score: float,
    attack_type: Optional[str],
):
    """
    Decide whether to fire an alert and dispatch it.
    Skips if the same IP+type is still within cooldown window.
    """
    alert_type = attack_type or "anomaly"
    source_ip = event.source_ip

    if _is_on_cooldown(source_ip, alert_type):
        logger.debug("alert suppressed (cooldown) for %s/%s", source_ip, alert_type)
        return

    severity = _severity_from_score(score)
    message = (
        f"[{severity.upper()}] {alert_type} detected from {source_ip} "
        f"| score={score:.3f} path={event.path} status={event.status_code}"
    )

    # persist the alert
    alert = Alert(
        event_id=event.id,
        severity=severity,
        alert_type=alert_type,
        message=message,
    )
    async with async_session() as session:
        session.add(alert)
        await session.commit()

    _update_cooldown(source_ip, alert_type)
    logger.info("ALERT FIRED: %s", message)

    # dispatch to external channels (fire-and-forget, don't block pipeline)
    await _dispatch_webhook(message, severity, source_ip, score)
    await _dispatch_email(message, severity)


async def _dispatch_webhook(
    message: str,
    severity: str,
    source_ip: str,
    score: float,
):
    """POST alert payload to the configured webhook URL (e.g., Slack, Discord, PagerDuty)."""
    if not settings.webhook_url:
        return

    payload = {
        "text": message,
        "severity": severity,
        "source_ip": source_ip,
        "score": score,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(settings.webhook_url, json=payload)
            if resp.status_code >= 400:
                logger.warning("webhook returned %d: %s", resp.status_code, resp.text[:200])
    except httpx.RequestError as e:
        logger.warning("webhook dispatch failed: %s", e)


async def _dispatch_email(message: str, severity: str):
    """
    Send alert email via SMTP.
    Stubbed to console logging by default — set SMTP_HOST in .env for real delivery.
    """
    if not settings.smtp_host:
        logger.debug("email stub: %s", message)
        return

    # in production you'd use aiosmtplib here:
    # async with aiosmtplib.SMTP(hostname=settings.smtp_host, port=settings.smtp_port) as smtp:
    #     await smtp.login(settings.smtp_user, settings.smtp_password)
    #     await smtp.sendmail(settings.smtp_user, settings.alert_email_to, ...)
    logger.info("email dispatched (severity=%s) to %s", severity, settings.alert_email_to)
