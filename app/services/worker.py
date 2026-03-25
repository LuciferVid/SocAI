"""
Background worker that consumes logs from Redis and processes them.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from app.models.database import async_session
from app.models.orm import Event
from app.services.log_parser import parse_log
from app.services.feature_engine import FeatureEngine
from app.services.scorer import get_scorer
from app.services.messaging import get_messaging_service
from app.services.alert_dispatcher import maybe_fire_alert
from app.services.ip_reputation import update_reputation
from app.api.routes_dashboard import broadcast_event
from config.settings import settings

logger = logging.getLogger("soc.worker")

# Singletons for the worker process
_feature_engine = None

async def get_feature_engine():
    global _feature_engine
    if _feature_engine is None:
        service = get_messaging_service()
        redis_conn = await service._get_redis()
        _feature_engine = FeatureEngine(redis_conn)
    return _feature_engine

async def process_message(raw_message: str):
    """Callback for Redis subscription."""
    try:
        data = json.loads(raw_message)
        parsed = parse_log(data)
        if not parsed:
            return

        # 1. Extract features (requires Redis for state)
        engine = await get_feature_engine()
        features = await engine.extract(parsed)
        
        # 2. Score event (ML models)
        scorer = get_scorer()
        score, attack_type = scorer.score(features, parsed)

        # 3. Persist event
        ts = parsed.get("timestamp")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                ts = datetime.now(timezone.utc)
        
        if ts:
            ts = ts.replace(tzinfo=None)
        
        async with async_session() as session:
            event = Event(
                timestamp=ts or datetime.now().replace(tzinfo=None),
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

            # 4. Fire alert via dispatcher (handles cooldowns & deduplication)
            if score >= settings.anomaly_threshold:
                await maybe_fire_alert(event, score, attack_type)

        # 5. Update IP reputation (tracks EWMA score per IP)
        await update_reputation(parsed["source_ip"], score, attack_type)

        # 6. Broadcast to dashboard
        await broadcast_event({
            "event": {
                "id": str(event.id),
                "timestamp": event.timestamp.isoformat(),
                "source_ip": event.source_ip,
                "method": event.method,
                "path": event.path,
                "status_code": event.status_code,
                "anomaly_score": event.anomaly_score,
                "attack_type": event.attack_type,
            }
        })

    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)

async def start_worker():
    """Startup function for the background consumer."""
    logger.info("Initializing background worker...")
    service = get_messaging_service()
    
    # Ensure models are loaded before we start consuming
    get_scorer()
    
    # Start consuming (blocks until cancelled)
    await service.consume(settings.ingestion_topic, process_message)

def run_worker_task():
    """Wrapper to run the worker as an asyncio Task."""
    return asyncio.create_task(start_worker())
