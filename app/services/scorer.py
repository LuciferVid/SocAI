"""
ML scoring orchestrator.
Loads the active model(s), scores feature vectors, and classifies attacks.
Supports hot-swap: a retrain trigger replaces the model files on disk
and this module reloads without requiring a full restart.
"""

import logging
from pathlib import Path
from typing import Optional

import numpy as np

from app.ml.isolation_forest import IsolationForestModel
from app.ml.autoencoder import AutoencoderModel
from app.ml.hybrid import hybrid_score
from config.settings import settings

logger = logging.getLogger("soc.scorer")


class Scorer:
    """
    Unified scoring interface.

    Scoring modes:
      - 'iforest': Isolation Forest only (default for Phase 1)
      - 'autoencoder': Autoencoder only (Phase 2)
      - 'hybrid': rules + ensemble average of both ML models (Phase 3)
    """

    def __init__(self, mode: str = "hybrid"):
        self.mode = mode
        self.iforest = IsolationForestModel()
        self.autoencoder = AutoencoderModel(input_dim=12)
        self._model_dir = Path(settings.model_dir)
        self._version: str = "v0"

    def load_models(self):
        """Load serialized models from disk."""
        iforest_path = self._model_dir / "isolation_forest.pkl"
        ae_path = self._model_dir / "autoencoder.pt"

        self.iforest.load(iforest_path)
        self.autoencoder.load(ae_path)
        logger.info("models loaded (mode=%s)", self.mode)

    def reload(self):
        """Hot-reload models from disk after a retrain."""
        logger.info("hot-reloading models")
        self.load_models()

    def score(
        self,
        features: np.ndarray,
        event: dict,
    ) -> tuple[float, Optional[str]]:
        """
        Score a single event.
        Returns (anomaly_score, attack_type).
        """
        if self.mode == "iforest":
            score = self.iforest.predict_single(features)
            attack_type = "anomaly" if score > settings.anomaly_threshold else None
            return score, attack_type

        elif self.mode == "autoencoder":
            score = self.autoencoder.predict_single(features)
            attack_type = "anomaly" if score > settings.anomaly_threshold else None
            return score, attack_type

        elif self.mode == "hybrid":
            # ensemble: average both model scores, then apply hybrid rules
            if_score = self.iforest.predict_single(features)
            ae_score = self.autoencoder.predict_single(features)
            ml_score = (if_score + ae_score) / 2.0
            return hybrid_score(ml_score, features, event)

        else:
            logger.error("unknown scoring mode: %s", self.mode)
            return 0.5, None


# module-level singleton — initialized when the consumer starts
scorer_instance: Scorer | None = None


def get_scorer() -> Scorer:
    global scorer_instance
    if scorer_instance is None:
        scorer_instance = Scorer(mode="hybrid")
        scorer_instance.load_models()
    return scorer_instance
