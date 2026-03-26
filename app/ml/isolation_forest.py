"""
Phase 1 — Isolation Forest anomaly detector.
Wraps sklearn's IsolationForest with a consistent interface
and normalizes scores to [0, 1] for downstream consumption.
"""

import logging
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest as SklearnIF

logger = logging.getLogger("soc.ml.iforest")


class IsolationForestModel:
    """
    Anomaly scorer using Isolation Forest.

    Score interpretation:
      - 0.0 = perfectly normal
      - 1.0 = extremely anomalous
    """

    def __init__(self, contamination: float = 0.05, n_estimators: int = 200):
        self.model = SklearnIF(
            n_estimators=n_estimators,
            contamination=contamination,
            random_state=42,
            n_jobs=1,
        )
        self._fitted = False

    def fit(self, X: np.ndarray):
        """Fit on historical 'normal' traffic data."""
        logger.info("training isolation forest on %d samples", X.shape[0])
        self.model.fit(X)
        self._fitted = True
        logger.info("training complete")

    def predict(self, X: np.ndarray) -> np.ndarray:
        """
        Score one or more feature vectors.
        Returns array of scores in [0, 1].
        """
        if not self._fitted:
            logger.warning("model not fitted — returning 0.5 for all inputs")
            return np.full(X.shape[0], 0.5)

        # sklearn returns negative scores: lower = more anomalous
        raw_scores = self.model.decision_function(X)
        # normalize: shift so that the decision boundary maps to ~0.5
        # more negative -> more anomalous -> higher output score
        normalized = 1.0 - (raw_scores - raw_scores.min()) / (
            (raw_scores.max() - raw_scores.min()) + 1e-8
        )
        return np.clip(normalized, 0.0, 1.0)

    def predict_single(self, features: np.ndarray) -> float:
        """Score a single feature vector, returns scalar."""
        return float(self.predict(features.reshape(1, -1))[0])

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.model, path)
        logger.info("model saved to %s", path)

    def load(self, path: Path):
        if not path.exists():
            logger.warning("model file not found at %s — starting unfitted", path)
            return
        self.model = joblib.load(path)
        self.model.set_params(n_jobs=1)
        self._fitted = True
        logger.info("model loaded from %s", path)
