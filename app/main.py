"""
FastAPI application factory with lifespan events.
Boots up all async services (DB, Redis) on startup
and tears them down cleanly on shutdown.
"""

import asyncio
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
    
    # Learned from deploy #1: Render free-tier PostgreSQL takes a while to spin up.
    # First attempt: no retries → app crashed if DB wasn't ready.
    # Second attempt: 10 retries × 5s = 50s total → Still failed sometimes.
    # Current: 60 retries × 3s = 180s (3 minutes) with exponential-ish backoff.
    # This gives plenty of slack for slow database provisioning.
    max_retries = 60
    retry_delay = 3
    for i in range(max_retries):
        try:
            await init_db()
            logger.info("database connection successful")
            break
        except Exception as e:
            if i == max_retries - 1:
                logger.error("Failed to connect to PostgreSQL after %d retries (%d seconds). Last error: %s", max_retries, max_retries * retry_delay, str(e))
                raise
            logger.warning("Database connection failed (retrying in %ds) [%d/%d] - Error: %s", retry_delay, i + 1, max_retries, str(e))
            await asyncio.sleep(retry_delay)


    logger.info("connecting to redis at %s", settings.redis_url)
    redis_pool = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=20,
    )
    await redis_pool.ping()
    logger.info("redis connected")

    # Start background worker for log processing
    from app.services.worker import run_worker_task
    application.state.worker_task = run_worker_task()

    # Start dummy threat traffic generator (for demo/hosting)
    from generator.sensor_agent import run_generator
    application.state.generator_task = asyncio.create_task(run_generator())

    logger.info("SOC pipeline is live")
    yield

    # --- shutdown ---
    logger.info("shutting down SOC pipeline")
    if hasattr(application.state, "worker_task"):
        application.state.worker_task.cancel()
        try:
            await application.state.worker_task
        except asyncio.CancelledError:
            pass

    if redis_pool:
        await redis_pool.close()
    await engine.dispose()
    logger.info("cleanup complete")


app = FastAPI(
    title="AI Threat Detection System",
    description="Real-time SOC powered by Redis streaming and ML anomaly detection",
    version="0.1.0",
    lifespan=lifespan,
)

# mount the live dashboard
from fastapi.responses import HTMLResponse
from pathlib import Path

@app.get("/", response_class=HTMLResponse)
async def get_landing():
    landing_path = Path(__file__).parent.parent / "dashboard" / "landing.html"
    with open(landing_path, "r") as f:
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
