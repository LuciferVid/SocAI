"""
Thin async Kafka producer wrapper.
JSON serialization, retry config, and idempotent delivery.
"""

import json
import logging

from aiokafka import AIOKafkaProducer

from config.settings import settings

logger = logging.getLogger("soc.kafka.producer")

_producer: AIOKafkaProducer | None = None


async def get_producer() -> AIOKafkaProducer:
    global _producer
    if _producer is None:
        _producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            acks="all",
            retry_backoff_ms=100,
            max_batch_size=16384,
        )
        await _producer.start()
        logger.info("kafka producer connected to %s", settings.kafka_bootstrap_servers)
    return _producer


async def produce(topic: str, value: dict, key: str | None = None):
    """Send a message to the given Kafka topic."""
    producer = await get_producer()
    key_bytes = key.encode("utf-8") if key else None
    await producer.send_and_wait(topic, value=value, key=key_bytes)


async def close_producer():
    global _producer
    if _producer:
        await _producer.stop()
        _producer = None
        logger.info("kafka producer closed")
