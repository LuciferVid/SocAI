"""
Messaging service for real-time log ingestion (Redis Pub/Sub).
"""

import json
import logging
import asyncio
from typing import Callable, Awaitable

import redis.asyncio as aioredis
from config.settings import settings

logger = logging.getLogger("soc.messaging")

class MessagingService:
    def __init__(self):
        self._redis = None
        self._pubsub = None

    async def _get_redis(self):
        if not self._redis:
            self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        return self._redis

    async def produce(self, topic: str, value: dict):
        """Publish a message to a Redis topic (channel)."""
        r = await self._get_redis()
        await r.publish(topic, json.dumps(value))

    async def consume(self, topic: str, handler: Callable[[str], Awaitable[None]]):
        """Subscribe to a Redis topic and handle incoming messages."""
        r = await self._get_redis()
        self._pubsub = r.pubsub()
        await self._pubsub.subscribe(topic)
        logger.info(f"Subscribed to {topic} (Redis Mode)")
        
        async for message in self._pubsub.listen():
            if message["type"] == "message":
                # Redis pubsub.listen() returns a dict with 'data'
                await handler(message["data"])

_service = MessagingService()

def get_messaging_service() -> MessagingService:
    return _service

async def produce(topic: str, value: dict):
    await _service.produce(topic, value)
