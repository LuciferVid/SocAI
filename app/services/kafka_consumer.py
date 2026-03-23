"""
Kafka consumer — the backbone of the streaming pipeline.
Consumes raw logs, runs them through parse → featurize → score → alert,
then persists results and broadcasts to the dashboard.

Design notes:
  - Manual offset commit for at-least-once delivery
  - Single consumer group; scale horizontally by adding partitions + consumers
  - Each message flows through the full pipeline in ~10-50ms
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from aiokafka import AIOKafkaConsumer

from config.settings import settings

logger = logging.getLogger("soc.kafka.consumer")

_consumer: AIOKafkaConsumer | None = None
_consumer_task: asyncio.Task | None = None


async def _process_message(raw_value: bytes):
    """
    Full streaming pipeline for a single message:
      1. Parse & normalize raw log
      2. Extract features (Redis sliding windows)
      3. Score with ML model
      4. Store event in PostgreSQL
      5. Update IP reputation
      6. Fire alert if above threshold
      7. Broadcast to dashboard WebSocket
    """
    # lazy imports to avoid circular deps at module load time
    from app.services.log_parser import parse_log
    from app.services.feature_engine import FeatureEngine
    from app.services.scorer import get_scorer
    from app.services.alert_dispatcher import maybe_fire_alert
    from app.services.ip_reputation import update_reputation
    from app.services.kafka_producer import produce
    from app.api.routes_dashboard import broadcast_event
    from app.models.database import async_session
    from app.models.orm import Event
    from app.main import redis_pool

    try:
        data = json.loads(raw_value.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning("skipping unparseable message: %s", e)
        return

    # step 1: parse and normalize
    parsed = parse_log(data)
    if parsed is None:
        logger.debug("parser returned None — skipping")
        return

    # step 2: extract features
    feature_engine = FeatureEngine(redis_pool)
    features = await feature_engine.extract(parsed)

    # step 3: score with ML
    scorer = get_scorer()
    anomaly_score, attack_type = scorer.score(features, parsed)

    # step 4: persist to PostgreSQL
    event_record = Event(
        timestamp=datetime.fromisoformat(parsed["timestamp"]),
        source_ip=parsed["source_ip"],
        dest_ip=parsed.get("dest_ip"),
        method=parsed.get("method"),
        path=parsed.get("path"),
        status_code=parsed.get("status_code"),
        user_agent=parsed.get("user_agent"),
        raw_log=parsed["raw_log"],
        log_source=parsed.get("log_source"),
        anomaly_score=anomaly_score,
        attack_type=attack_type,
    )

    async with async_session() as session:
        session.add(event_record)
        await session.commit()
        await session.refresh(event_record)

    # step 5: update IP reputation
    await update_reputation(parsed["source_ip"], anomaly_score, attack_type)

    # step 6: fire alert if needed
    if anomaly_score >= settings.anomaly_threshold:
        await maybe_fire_alert(event_record, anomaly_score, attack_type)

        # publish to scored topic for downstream consumers
        scored_payload = {
            "event_id": str(event_record.id),
            "source_ip": parsed["source_ip"],
            "anomaly_score": anomaly_score,
            "attack_type": attack_type,
            "timestamp": parsed["timestamp"],
        }
        await produce(settings.kafka_topic_scored, scored_payload)

    # step 7: broadcast to dashboard
    await broadcast_event({
        "event_id": str(event_record.id),
        "timestamp": parsed["timestamp"],
        "source_ip": parsed["source_ip"],
        "method": parsed.get("method"),
        "path": parsed.get("path"),
        "status_code": parsed.get("status_code"),
        "anomaly_score": round(anomaly_score, 4),
        "attack_type": attack_type,
    })


async def _consume_loop():
    """Main consume loop — reads and processes messages one at a time."""
    global _consumer

    _consumer = AIOKafkaConsumer(
        settings.kafka_topic_raw,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_consumer_group,
        auto_offset_reset="latest",
        enable_auto_commit=False,
        value_deserializer=lambda v: v,  # raw bytes, decoded in _process_message
    )
    await _consumer.start()
    logger.info(
        "consumer started — group=%s topic=%s",
        settings.kafka_consumer_group, settings.kafka_topic_raw,
    )

    try:
        async for msg in _consumer:
            try:
                await _process_message(msg.value)
            except Exception:
                logger.exception("error processing message at offset %d", msg.offset)
            # commit after each message (at-least-once semantics)
            await _consumer.commit()
    finally:
        await _consumer.stop()
        logger.info("consumer stopped")


async def start_consumers():
    """Called from app lifespan — kicks off the consumer as a background task."""
    global _consumer_task
    _consumer_task = asyncio.create_task(_consume_loop())
    logger.info("consumer task scheduled")


async def stop_consumers():
    """Graceful shutdown."""
    global _consumer_task, _consumer
    if _consumer:
        await _consumer.stop()
    if _consumer_task:
        _consumer_task.cancel()
        try:
            await _consumer_task
        except asyncio.CancelledError:
            pass
    logger.info("consumer shutdown complete")
