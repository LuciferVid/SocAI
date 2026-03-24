import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import FastAPI, Request, Response
import uvicorn
from aiokafka import AIOKafkaProducer

from config.settings import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("soc.honeypot")

app = FastAPI(title="SOCAI Honeypot - Real Traffic Ingestion")

# Global Kafka producer
producer = None

@app.on_event("startup")
async def startup_event():
    logger.info("Honeypot started — ingesting live traffic to %s (Redis Mode)", settings.ingestion_topic)

@app.on_event("shutdown")
async def shutdown_event():
    from app.services.kafka_producer import close_producer
    await close_producer()
    logger.info("Honeypot stopped")

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def catch_all(request: Request, path: str):
    """
    Catches EVERY single HTTP request sent to this server,
    packages it as a SOC event, and ships it to Kafka.
    """
    source_ip = request.client.host if request.client else "127.0.0.1"
    
    # If running behind a proxy like ngrok, use the forward headers
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        source_ip = forwarded_for.split(",")[0].strip()

    method = request.method
    full_path = f"/{path}"
    if request.url.query:
        full_path += f"?{request.url.query}"
        
    user_agent = request.headers.get("user-agent", "")
    
    # We will pretend the honeypot always returns 200 OK or 404
    # To make it interesting to scanners, return 200 for typical admin paths, 404 otherwise.
    status_code = 200 if any(x in full_path for x in ["admin", "login", "wp-", "config", "env", "api"]) else 404

    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_ip": source_ip,
        "dest_ip": "honeypot", # Our honeypot identifier
        "method": method,
        "path": full_path,
        "status_code": status_code,
        "user_agent": user_agent,
        "log_source": "http",
    }
    
    # Add raw log for audit
    event["raw_log"] = json.dumps({
        "headers": dict(request.headers),
        "query": request.url.query
    })

    # Produce to Messaging Layer
    from app.services.messaging import produce
    await produce(settings.ingestion_topic, event)
    logger.info("Captured %s %s from %s", method, full_path, source_ip)

    # Return a fake generic response to keep scanners probing
    return Response(
        content='<html><body><p>Access OK</p></body></html>' if status_code == 200 else '<html><body><h1>Not Found</h1></body></html>',
        status_code=status_code,
        media_type="text/html"
    )

if __name__ == "__main__":
    # Run the honeypot on port 8080
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="warning")
