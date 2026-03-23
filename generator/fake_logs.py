"""
Fake log generator that produces realistic mixed log events.
Simulates HTTP access logs, SSH auth, and API gateway traffic.
Embeds attack patterns at a configurable rate (~5%) so the ML
model has something to detect out of the box.
"""

import asyncio
import json
import random
import logging
from datetime import datetime, timezone

from aiokafka import AIOKafkaProducer

from config.settings import settings

logger = logging.getLogger("soc.generator")

# realistic-ish pools
NORMAL_IPS = [f"192.168.1.{i}" for i in range(10, 60)]
ATTACKER_IPS = ["10.0.0.99", "10.0.0.100", "203.0.113.42", "198.51.100.7"]
METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH"]
NORMAL_PATHS = [
    "/api/users", "/api/products", "/api/orders", "/api/health",
    "/api/auth/login", "/api/auth/refresh", "/api/search",
    "/api/dashboard", "/api/settings", "/api/notifications",
    "/static/main.js", "/static/style.css", "/index.html",
]
SUSPICIOUS_PATHS = [
    "/admin/shell", "/wp-admin/install.php", "/.env",
    "/api/../../etc/passwd", "/api/debug/vars",
    "/cgi-bin/test.cgi", "/phpmyadmin/index.php",
]
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) Safari/17.0",
    "python-requests/2.31.0",
    "curl/8.4.0",
    "PostmanRuntime/7.36.0",
]
ATTACK_USER_AGENTS = [
    "sqlmap/1.7",
    "Nikto/2.5",
    "dirbuster/1.0",
    "",
]


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normal_event() -> dict:
    """Generate a typical, benign log entry."""
    return {
        "timestamp": _ts(),
        "source_ip": random.choice(NORMAL_IPS),
        "dest_ip": "10.0.0.1",
        "method": random.choice(["GET", "GET", "GET", "POST"]),  # reads dominate
        "path": random.choice(NORMAL_PATHS),
        "status_code": random.choice([200, 200, 200, 201, 301, 304, 400, 404]),
        "user_agent": random.choice(USER_AGENTS),
        "log_source": "http",
    }


def _brute_force_event() -> dict:
    """Simulates a failed login burst from an attacker IP."""
    return {
        "timestamp": _ts(),
        "source_ip": random.choice(ATTACKER_IPS),
        "dest_ip": "10.0.0.1",
        "method": "POST",
        "path": "/api/auth/login",
        "status_code": 401,
        "user_agent": random.choice(ATTACK_USER_AGENTS),
        "log_source": "http",
    }


def _ddos_spike_event() -> dict:
    """Rapid-fire GET flood from the same IP."""
    ip = random.choice(ATTACKER_IPS)
    return {
        "timestamp": _ts(),
        "source_ip": ip,
        "dest_ip": "10.0.0.1",
        "method": "GET",
        "path": random.choice(NORMAL_PATHS),
        "status_code": 200,
        "user_agent": "",
        "log_source": "http",
    }


def _suspicious_api_event() -> dict:
    """Path traversal, admin probe, or scanner traffic."""
    return {
        "timestamp": _ts(),
        "source_ip": random.choice(ATTACKER_IPS),
        "dest_ip": "10.0.0.1",
        "method": random.choice(METHODS),
        "path": random.choice(SUSPICIOUS_PATHS),
        "status_code": random.choice([403, 404, 500]),
        "user_agent": random.choice(ATTACK_USER_AGENTS),
        "log_source": "http",
    }


def _ssh_auth_event() -> dict:
    """SSH login attempt — ~20% are failed from attacker IPs."""
    is_attack = random.random() < 0.2
    return {
        "timestamp": _ts(),
        "source_ip": random.choice(ATTACKER_IPS if is_attack else NORMAL_IPS),
        "dest_ip": "10.0.0.1",
        "method": "SSH",
        "path": "/ssh/auth",
        "status_code": 401 if is_attack else 200,
        "user_agent": "OpenSSH_9.0",
        "log_source": "ssh",
    }


def generate_event() -> dict:
    """Pick an event type — 95% normal, 5% attack patterns."""
    roll = random.random()
    if roll < 0.02:
        event = _brute_force_event()
    elif roll < 0.035:
        event = _ddos_spike_event()
    elif roll < 0.05:
        event = _suspicious_api_event()
    elif roll < 0.10:
        event = _ssh_auth_event()
    else:
        event = _normal_event()

    # stash the whole dict as raw_log for auditability
    event["raw_log"] = json.dumps(event)
    return event


async def run_generator(
    events_per_second: float = 10.0,
    total_events: int | None = None,
):
    """
    Main entry: produces fake logs to the Kafka raw topic.
    - events_per_second: baseline throughput
    - total_events: if set, stop after N events; otherwise run forever
    """
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )
    await producer.start()
    logger.info(
        "generator started — producing to %s at ~%.0f eps",
        settings.kafka_topic_raw, events_per_second,
    )

    count = 0
    try:
        while total_events is None or count < total_events:
            event = generate_event()
            await producer.send_and_wait(settings.kafka_topic_raw, event)
            count += 1

            if count % 100 == 0:
                logger.info("produced %d events", count)

            # inject burst: occasionally fire 20 rapid events from one attacker
            if random.random() < 0.005:
                burst_ip = random.choice(ATTACKER_IPS)
                logger.info("injecting DDoS burst from %s", burst_ip)
                for _ in range(20):
                    burst = _ddos_spike_event()
                    burst["source_ip"] = burst_ip
                    burst["raw_log"] = json.dumps(burst)
                    await producer.send_and_wait(settings.kafka_topic_raw, burst)
                    count += 1

            await asyncio.sleep(1.0 / events_per_second)
    finally:
        await producer.stop()
        logger.info("generator stopped after %d events", count)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_generator())
