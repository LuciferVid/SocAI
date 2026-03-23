"""
Retrain API route.
Triggers background model retraining with feedback-labeled data.
"""

import logging
from fastapi import APIRouter, BackgroundTasks

from app.services.retrain import retrain_models

logger = logging.getLogger("soc.api.retrain")
router = APIRouter()


@router.post("/")
async def trigger_retrain(background_tasks: BackgroundTasks):
    """
    Kick off model retraining as a background task.
    Returns immediately; models will hot-swap once training completes.
    """
    background_tasks.add_task(retrain_models)
    logger.info("retrain task queued")
    return {
        "status": "retrain_queued",
        "message": "Models will be retrained in the background. "
                   "Check logs for progress.",
    }
