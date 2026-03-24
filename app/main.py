"""
FastAPI application factory with lifespan events.
Boots up all async services (DB, Redis, Kafka consumers) on startup
and tears them down cleanly on shutdown.
"""

import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.models.database import init_db, engine
from config.settings import settings

logger = logging.getLogger("soc")

# module-level references so other modules can import them
redis_pool: aioredis.Redis | None = None


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup / shutdown lifecycle."""
    global redis_pool

    # --- startup ---
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    logger.info("initializing database tables")
    await init_db()

    logger.info("connecting to redis at %s", settings.redis_url)
    redis_pool = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=20,
    )
    await redis_pool.ping()
    logger.info("redis connected")

    # import here to avoid circular deps — consumers need redis & db
    from app.services.kafka_consumer import start_consumers
    await start_consumers()

    logger.info("SOC pipeline is live")
    yield

    # --- shutdown ---
    logger.info("shutting down SOC pipeline")
    from app.services.kafka_consumer import stop_consumers
    await stop_consumers()

    if redis_pool:
        await redis_pool.close()
    await engine.dispose()
    logger.info("cleanup complete")


app = FastAPI(
    title="AI Threat Detection System",
    description="Real-time SOC powered by streaming ML anomaly detection",
    version="0.1.0",
    lifespan=lifespan,
)

# mount the live dashboard
from fastapi.responses import HTMLResponse

@app.get("/", response_class=HTMLResponse)
async def get_landing():
    with open("dashboard/landing.html", "r") as f:
        return f.read()

app.mount("/dashboard", StaticFiles(directory="dashboard", html=True), name="dashboard")

# register API routers
from app.api.routes_events import router as events_router
from app.api.routes_alerts import router as alerts_router
from app.api.routes_dashboard import router as dashboard_router
from app.api.routes_reputation import router as reputation_router
from app.api.routes_retrain import router as retrain_router

app.include_router(events_router, prefix="/api/events", tags=["events"])
app.include_router(alerts_router, prefix="/api/alerts", tags=["alerts"])
app.include_router(dashboard_router, tags=["dashboard"])
app.include_router(reputation_router, prefix="/api/reputation", tags=["reputation"])
app.include_router(retrain_router, prefix="/api/retrain", tags=["retrain"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "soc-api"}
