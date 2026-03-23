"""
Standalone demo mode — runs without Docker / Kafka / PostgreSQL / Redis.
Uses SQLite, in-memory feature counters, and an internal event loop
to demonstrate the full pipeline end-to-end.
"""

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Set

import numpy as np
import redis.asyncio as aioredis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func, desc, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("soc.demo")

# ─── In-memory SQLite for demo ───
from app.models.database import Base
from app.models.orm import Event, Alert, IPReputation

DEMO_DB_URL = "sqlite+aiosqlite:///demo_soc.db"
demo_engine = create_async_engine(DEMO_DB_URL, echo=False)
demo_session = async_sessionmaker(demo_engine, class_=AsyncSession, expire_on_commit=False)

# ─── In-memory feature store (replaces Redis) ───
class InMemoryFeatureStore:
    """Simple dict-based feature store for demo — replaces Redis sorted sets."""

    def __init__(self):
        self._requests: dict[str, list[float]] = defaultdict(list)  # ip -> [timestamps]
        self._failures: dict[str, list[float]] = defaultdict(list)
        self._paths: dict[str, dict[str, float]] = defaultdict(dict)
        self._statuses: dict[str, list[tuple[int, float]]] = defaultdict(list)

    def record(self, ip: str, path: str, status: int, now: float):
        self._requests[ip].append(now)
        if status >= 400:
            self._failures[ip].append(now)
        self._paths[ip][path] = now
        self._statuses[ip].append((status, now))
        # prune old entries (> 15 min)
        cutoff = now - 900
        self._requests[ip] = [t for t in self._requests[ip] if t > cutoff]
        self._failures[ip] = [t for t in self._failures[ip] if t > cutoff]
        self._statuses[ip] = [(s, t) for s, t in self._statuses[ip] if t > cutoff]

    def extract(self, ip: str, path: str, status: int, method: str) -> np.ndarray:
        now = time.time()
        self.record(ip, path, status, now)

        c1m = now - 60
        c5m = now - 300

        req_1m = sum(1 for t in self._requests[ip] if t > c1m)
        req_5m = sum(1 for t in self._requests[ip] if t > c5m)
        fail_1m = sum(1 for t in self._failures[ip] if t > c1m)
        fail_5m = sum(1 for t in self._failures[ip] if t > c5m)
        unique_paths = sum(1 for p, t in self._paths[ip].items() if t > c1m)

        recent_statuses = [s for s, t in self._statuses[ip] if t > c1m]
        avg_status = sum(recent_statuses) / len(recent_statuses) if recent_statuses else 0.0

        burst_5s = sum(1 for t in self._requests[ip] if t > now - 5)
        burst_rate = burst_5s / 5.0

        return np.array([
            req_1m, req_5m, fail_1m, fail_5m, unique_paths,
            avg_status,
            1.0 if method == "POST" else 0.0,
            1.0 if "/auth" in path or "/login" in path or "/ssh" in path else 0.0,
            1.0 if status == 401 else 0.0,
            1.0 if status == 403 else 0.0,
            1.0 if status == 500 else 0.0,
            burst_rate,
        ], dtype=np.float32)


feature_store = InMemoryFeatureStore()

# ─── WebSocket clients ───
ws_clients: Set[WebSocket] = set()

# ─── Load ML models ───
from app.ml.isolation_forest import IsolationForestModel
from app.ml.autoencoder import AutoencoderModel
from app.ml.hybrid import hybrid_score

iforest = IsolationForestModel()
autoencoder = AutoencoderModel(input_dim=12)


def load_models():
    artifacts = Path(settings.model_dir)
    iforest.load(artifacts / "isolation_forest.pkl")
    autoencoder.load(artifacts / "autoencoder.pt")


# ─── Generator (inline) ───
from generator.fake_logs import generate_event

# ─── Pipeline stats ───
stats = {
    "total_events": 0,
    "total_alerts": 0,
    "events_per_second": 0,
}


async def process_event(event: dict):
    """Run one event through the full pipeline."""
    from app.services.log_parser import parse_log

    parsed = parse_log(event)
    if not parsed:
        return

    ip = parsed["source_ip"]
    path = parsed.get("path", "/")
    status = parsed.get("status_code") or 200
    method = parsed.get("method", "GET")

    # extract features
    features = feature_store.extract(ip, path, status, method)

    # score with both models
    if_score = iforest.predict_single(features)
    ae_score = autoencoder.predict_single(features)
    ml_score = (if_score + ae_score) / 2.0
    score, attack_type = hybrid_score(ml_score, features, parsed)

    # persist event
    ts_str = parsed.get("timestamp", datetime.now(timezone.utc).isoformat())
    try:
        ts = datetime.fromisoformat(ts_str)
    except:
        ts = datetime.now(timezone.utc)

    event_record = Event(
        timestamp=ts,
        source_ip=ip,
        dest_ip=parsed.get("dest_ip"),
        method=method,
        path=path,
        status_code=status,
        user_agent=parsed.get("user_agent"),
        raw_log=parsed.get("raw_log", ""),
        log_source=parsed.get("log_source"),
        anomaly_score=score,
        attack_type=attack_type,
    )

    async with demo_session() as session:
        session.add(event_record)
        await session.commit()
        await session.refresh(event_record)

    stats["total_events"] += 1

    # fire alert if threshold
    severity = None
    if score >= settings.anomaly_threshold:
        severity = "critical" if score >= 0.95 else "high" if score >= 0.85 else "medium"
        alert = Alert(
            event_id=event_record.id,
            severity=severity,
            alert_type=attack_type or "anomaly",
            message=f"[{severity}] {attack_type or 'anomaly'} from {ip} | score={score:.3f}",
        )
        async with demo_session() as session:
            session.add(alert)
            await session.commit()
        stats["total_alerts"] += 1

        # update IP reputation
        async with demo_session() as session:
            result = await session.execute(select(IPReputation).where(IPReputation.ip == ip))
            rep = result.scalar_one_or_none()
            if rep is None:
                rep = IPReputation(
                    ip=ip, total_events=1, total_alerts=1,
                    anomaly_sum=score, reputation_score=max(0, 1.0 - score),
                    tag="suspicious" if score < 0.9 else "blocked",
                )
                session.add(rep)
            else:
                rep.total_events += 1
                rep.total_alerts += 1
                rep.anomaly_sum += score
                rep.reputation_score = 0.1 * (1.0 - score) + 0.9 * rep.reputation_score
                rep.tag = "blocked" if rep.reputation_score <= 0.25 else "suspicious" if rep.reputation_score <= 0.45 else "trusted"
                rep.last_seen = datetime.now(timezone.utc)
            await session.commit()

    # broadcast to dashboard
    payload = json.dumps({
        "event_id": str(event_record.id),
        "timestamp": ts.isoformat(),
        "source_ip": ip,
        "method": method,
        "path": path,
        "status_code": status,
        "anomaly_score": round(score, 4),
        "attack_type": attack_type,
        "severity": severity,
    })

    dead = set()
    for ws in ws_clients:
        try:
            await ws.send_text(payload)
        except:
            dead.add(ws)
    ws_clients.difference_update(dead)


async def generate_loop():
    """Background task that generates and processes events."""
    logger.info("starting event generator at ~10 eps")
    import random
    from generator.fake_logs import generate_event, ATTACKER_IPS, _ddos_spike_event

    while True:
        event = generate_event()
        await process_event(event)

        # occasional burst
        if random.random() < 0.008:
            burst_ip = random.choice(ATTACKER_IPS)
            logger.info("💥 injecting burst from %s", burst_ip)
            for _ in range(15):
                burst = _ddos_spike_event()
                burst["source_ip"] = burst_ip
                burst["raw_log"] = json.dumps(burst)
                await process_event(burst)
                await asyncio.sleep(0.02)

        await asyncio.sleep(0.1)


_gen_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(application: FastAPI):
    global _gen_task

    # init DB
    async with demo_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("demo database initialized (SQLite)")

    # load models
    load_models()
    logger.info("ML models loaded")

    # start generator
    _gen_task = asyncio.create_task(generate_loop())
    logger.info("🚀 demo pipeline is live — open http://localhost:8000/dashboard")

    yield

    if _gen_task:
        _gen_task.cancel()
    await demo_engine.dispose()


# ─── FastAPI app ───
app = FastAPI(
    title="AI Threat Detection System (Demo Mode)",
    version="0.1.0-demo",
    lifespan=lifespan,
)

app.mount("/dashboard", StaticFiles(directory="dashboard", html=True), name="dashboard")


@app.get("/health")
async def health():
    return {"status": "ok", "mode": "demo", "stats": stats}


@app.websocket("/ws/live")
async def ws_live(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    logger.info("dashboard client connected (%d total)", len(ws_clients))
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(ws)


# ─── API routes (simplified for demo) ───
from fastapi import Query, HTTPException

@app.get("/api/events/")
async def list_events(skip: int = 0, limit: int = 50, source_ip: Optional[str] = None, min_score: Optional[float] = None):
    async with demo_session() as session:
        query = select(Event).order_by(desc(Event.created_at))
        if source_ip:
            query = query.where(Event.source_ip == source_ip)
        if min_score is not None:
            query = query.where(Event.anomaly_score >= min_score)
        query = query.offset(skip).limit(limit)
        result = await session.execute(query)
        events = result.scalars().all()
        return [
            {
                "id": str(e.id), "timestamp": e.timestamp.isoformat() if e.timestamp else "",
                "source_ip": e.source_ip, "method": e.method, "path": e.path,
                "status_code": e.status_code, "anomaly_score": e.anomaly_score,
                "attack_type": e.attack_type, "log_source": e.log_source,
            }
            for e in events
        ]

@app.get("/api/events/count")
async def event_count():
    return {"count": stats["total_events"]}

@app.get("/api/alerts/")
async def list_alerts(limit: int = 50):
    async with demo_session() as session:
        result = await session.execute(
            select(Alert).order_by(desc(Alert.created_at)).limit(limit)
        )
        alerts = result.scalars().all()
        return [
            {
                "id": str(a.id), "event_id": str(a.event_id),
                "severity": a.severity, "alert_type": a.alert_type,
                "message": a.message, "resolved": a.resolved,
                "created_at": a.created_at.isoformat() if a.created_at else "",
            }
            for a in alerts
        ]

@app.get("/api/alerts/stats")
async def alert_stats():
    return {
        "total_alerts": stats["total_alerts"],
        "active_alerts": stats["total_alerts"],
        "critical_active": 0,
    }

@app.get("/api/reputation/{ip}")
async def get_reputation(ip: str):
    async with demo_session() as session:
        result = await session.execute(select(IPReputation).where(IPReputation.ip == ip))
        rep = result.scalar_one_or_none()
        if not rep:
            raise HTTPException(404, "IP not found")
        return {
            "ip": rep.ip, "total_events": rep.total_events,
            "total_alerts": rep.total_alerts, "reputation_score": rep.reputation_score,
            "tag": rep.tag,
        }

@app.post("/api/retrain/")
async def trigger_retrain():
    return {"status": "retrain_queued", "message": "Retrain queued (demo mode)"}
