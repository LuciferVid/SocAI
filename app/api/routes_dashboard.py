"""
Dashboard WebSocket route + static file serving.
Pushes scored events and alerts to connected dashboard clients in real-time.
"""

import json
import logging
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger("soc.api.dashboard")
router = APIRouter()

# track connected WebSocket clients
_connected_clients: Set[WebSocket] = set()


@router.websocket("/ws/live")
async def websocket_live(ws: WebSocket):
    """
    WebSocket endpoint for the live dashboard.
    Clients connect here and receive a stream of scored events and alerts.
    """
    await ws.accept()
    _connected_clients.add(ws)
    logger.info("dashboard client connected (%d total)", len(_connected_clients))

    try:
        # keep the connection alive — we mainly push from the server side
        while True:
            # listen for any client messages (e.g., filter commands in the future)
            data = await ws.receive_text()
            logger.debug("received from dashboard client: %s", data[:100])
    except WebSocketDisconnect:
        pass
    finally:
        _connected_clients.discard(ws)
        logger.info("dashboard client disconnected (%d remaining)", len(_connected_clients))


async def broadcast_event(payload: dict):
    """
    Push a scored event to all connected dashboard clients.
    Called from the Kafka consumer after each event is processed.
    """
    if not _connected_clients:
        return

    message = json.dumps(payload)
    dead = set()
    for ws in _connected_clients:
        try:
            await ws.send_text(message)
        except Exception:
            dead.add(ws)

    # clean up stale connections
    _connected_clients.difference_update(dead)
