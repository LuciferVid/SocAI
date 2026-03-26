"""
Model training pipeline.
Can be run as a CLI script or triggered via the /api/retrain endpoint.
Loads data from PostgreSQL (labeled events) or generates synthetic training data,
then trains both the Isolation Forest and Autoencoder models.
"""

import asyncio
import logging
from pathlib import Path

import numpy as np
from sqlalchemy import select, text

from app.ml.isolation_forest import IsolationForestModel
from app.ml.autoencoder import AutoencoderModel
from app.models.database import async_session
from app.models.orm import Event
from config.settings import settings

logger = logging.getLogger("soc.ml.train")


def generate_synthetic_training_data(n_normal: int = 5000, n_attack: int = 250) -> np.ndarray:
    """
    Generate synthetic feature vectors for initial model training.
    Used before we have enough real logged events.

    Feature order matches FeatureEngine.FEATURE_NAMES:
      [ip_req_1m, ip_req_5m, ip_fail_1m, ip_fail_5m, unique_paths_1m,
       avg_status_1m, is_post, is_auth, is_401, is_403, is_500, burst_rate]
    """
    rng = np.random.default_rng(42)

    # normal traffic patterns
    normal = np.column_stack([
        rng.poisson(5, n_normal),          # ip_req_1m: ~5 requests
        rng.poisson(20, n_normal),         # ip_req_5m: ~20
        rng.poisson(0.3, n_normal),        # ip_fail_1m: rare failures
        rng.poisson(1, n_normal),          # ip_fail_5m
        rng.poisson(3, n_normal),          # unique_paths_1m
        rng.normal(220, 30, n_normal),     # avg_status: ~200s
        rng.binomial(1, 0.2, n_normal),    # is_post: 20%
        rng.binomial(1, 0.1, n_normal),    # is_auth: 10%
        rng.binomial(1, 0.02, n_normal),   # is_401: 2%
        rng.binomial(1, 0.01, n_normal),   # is_403: 1%
        rng.binomial(1, 0.005, n_normal),  # is_500: 0.5%
        rng.exponential(0.5, n_normal),    # burst_rate: low
    ]).astype(np.float32)

    # we only train on normal data (unsupervised) — the model learns "what normal looks like"
    # attacks are NOT used in training; they're for validation only
    logger.info("generated %d synthetic normal samples", n_normal)
    return normal


async def load_training_data_from_db() -> np.ndarray | None:
    """
    Load feature data from scored events in the database.
    Only uses events labeled as 'normal' (from the feedback loop).
    Falls back to None if insufficient data.
    """
    async with async_session() as session:
        result = await session.execute(
            text("""
                SELECT anomaly_score FROM events
                WHERE label = 'normal' OR label IS NULL
                LIMIT 10000
            """)
        )
        rows = result.fetchall()

    if len(rows) < 100:
        logger.info("only %d labeled events in DB — not enough for retraining", len(rows))
        return None

    logger.info("loaded %d events from DB for retraining", len(rows))
    # Feature vector storage is planned for a future release — requires
    # persisting the full feature array alongside each event during ingestion
    return None


def train_models(
    X_train: np.ndarray | None = None,
    model_dir: str | None = None,
):
    """
    Train both ML models and save artifacts.
    If no training data is provided, generates synthetic data.
    """
    if model_dir is None:
        model_dir = settings.model_dir
    artifacts = Path(model_dir)

    if X_train is None:
        X_train = generate_synthetic_training_data()

    # Phase 1: Isolation Forest
    iforest = IsolationForestModel()
    iforest.fit(X_train)
    iforest.save(artifacts / "isolation_forest.pkl")

    # Phase 2: Autoencoder
    autoencoder = AutoencoderModel(input_dim=X_train.shape[1])
    autoencoder.fit(X_train, epochs=50, batch_size=256)
    autoencoder.save(artifacts / "autoencoder.pt")

    logger.info("all models trained and saved to %s", artifacts)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    train_models()
