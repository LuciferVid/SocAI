"""
Thin async Kafka producer wrapper.
JSON serialization, retry config, and idempotent delivery.
"""

import json
import logging

from aiokafka import AIOKafkaProducer

from config.settings import settings

logger = logging.getLogger("soc.kafka.producer")

from app.services.messaging import get_messaging_provider

_provider = None

async def produce(topic: str, value: dict, key: str | None = None):
    global _provider
    if _provider is None:
        _provider = get_messaging_provider()
        await _provider.start()
    await _provider.produce(topic, value, key)

async def close_producer():
    global _provider
    if _provider:
        await _provider.stop()
        _provider = None
