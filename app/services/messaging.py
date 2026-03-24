"""
Abstraction layer for messaging (Kafka vs Redis).
Enables the system to run on high-performance Kafka or lightweight Redis Pub/Sub.
"""

import json
import logging
import asyncio
from typing import Callable, Awaitable

from config.settings import settings

logger = logging.getLogger("soc.messaging")

class MessagingProvider:
    async def start(self):
        pass

    async def stop(self):
        pass

    async def produce(self, topic: str, value: dict, key: str | None = None):
        raise NotImplementedError

    async def consume(self, topic: str, handler: Callable[[bytes], Awaitable[None]]):
        raise NotImplementedError

class KafkaProvider(MessagingProvider):
    def __init__(self):
        from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
        self._producer = None
        self._consumer = None
        self._stop_event = asyncio.Event()

    async def start(self):
        from aiokafka import AIOKafkaProducer
        if not self._producer:
            self._producer = AIOKafkaProducer(
                bootstrap_servers=settings.kafka_bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            )
            await self._producer.start()
            logger.info("Kafka producer started")

    async def stop(self):
        if self._producer:
            await self._producer.stop()
        if self._consumer:
            await self._consumer.stop()
        self._stop_event.set()

    async def produce(self, topic: str, value: dict, key: str | None = None):
        if not self._producer: await self.start()
        key_bytes = key.encode("utf-8") if key else None
        await self._producer.send_and_wait(topic, value=value, key=key_bytes)

    async def consume(self, topic: str, handler: Callable[[bytes], Awaitable[None]]):
        from aiokafka import AIOKafkaConsumer
        self._consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=settings.kafka_consumer_group,
            auto_offset_reset="latest",
            enable_auto_commit=True,
        )
        await self._consumer.start()
        logger.info(f"Kafka consumer started on topic {topic}")
        try:
            async for msg in self._consumer:
                await handler(msg.value)
        finally:
            await self._consumer.stop()

class RedisProvider(MessagingProvider):
    def __init__(self):
        self._redis = None
        self._pubsub = None

    async def _get_redis(self):
        if not self._redis:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(settings.redis_url)
        return self._redis

    async def produce(self, topic: str, value: dict, key: str | None = None):
        r = await self._get_redis()
        await r.publish(topic, json.dumps(value))

    async def consume(self, topic: str, handler: Callable[[bytes], Awaitable[None]]):
        r = await self._get_redis()
        self._pubsub = r.pubsub()
        await self._pubsub.subscribe(topic)
        logger.info(f"Redis consumer subscribed to {topic}")
        
        async for message in self._pubsub.listen():
            if message["type"] == "message":
                await handler(message["data"])

def get_messaging_provider() -> MessagingProvider:
    if settings.messaging_type.lower() == "redis":
        return RedisProvider()
    return KafkaProvider()
