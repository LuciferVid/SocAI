"""
Background worker that consumes logs from Redis and processes them.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from app.models.database import session_factory
from app.models.orm import Event, Alert, IPReputation
from app.services.log_parser import parse_log
from app.services.feature_engine import extract_features
from app.services.scorer import score_event
from app.services.messaging import get_messaging_service
from config.settings import settings

logger = logging.getLogger("soc.worker")

async def process_message(raw_message: str):
    """Callback for Redis subscription."""
    try:
        data = json.loads(raw_message)
        parsed = parse_log(data)
        if not parsed:
            return

        # extract features & score
        features = extract_features(parsed)
        score, attack_type = score_event(features, parsed)

        # persist event
        async with session_factory() as session:
            event = Event(
                source_ip=parsed["source_ip"],
                dest_ip=parsed.get("dest_ip"),
                method=parsed.get("method"),
                path=parsed.get("path"),
                status_code=parsed.get("status_code"),
                user_agent=parsed.get("user_agent"),
                raw_log=parsed.get("raw_log", ""),
                log_source=parsed.get("log_source"),
                anomaly_score=score,
                attack_type=attack_type,
            )
            session.add(event)
            await session.commit()
            await session.refresh(event)

            # check for alerts
            if score >= settings.anomaly_threshold:
                severity = "critical" if score >= 0.95 else "high" if score >= 0.85 else "medium"
                alert = Alert(
                    event_id=event.id,
                    severity=severity,
                    alert_type=attack_type or "anomaly",
                    message=f"[{severity.upper()}] Anomaly detected from {event.source_ip}",
                )
                session.add(alert)
                await session.commit()
                logger.warning(f"ALERT: {alert.message} | Score: {score:.3f}")

    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)

async def start_worker():
    """Startup function for the background consumer."""
    service = get_messaging_service()
    # this will block, so it should be run in a task
    await service.consume(settings.ingestion_topic, process_message)

def run_worker_task():
    return asyncio.create_task(start_worker())
