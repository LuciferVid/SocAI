"""
Phase 2 — Autoencoder anomaly detector (PyTorch).
Reconstruction error = anomaly score.
Higher error → more anomalous.
"""

import logging
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

torch.set_num_threads(1)

logger = logging.getLogger("soc.ml.autoencoder")


class Autoencoder(nn.Module):
    """
    Symmetric autoencoder: input → 32 → 16 → 8 → 16 → 32 → input.
    Trained on normal traffic; anomalies produce high reconstruction error.
    """

    def __init__(self, input_dim: int = 12):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, 32),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(32, 16),
            nn.ReLU(),
            nn.Linear(16, 8),
            nn.ReLU(),
        )
        self.decoder = nn.Sequential(
            nn.Linear(8, 16),
            nn.ReLU(),
            nn.Linear(16, 32),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(32, input_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        encoded = self.encoder(x)
        decoded = self.decoder(encoded)
        return decoded


class AutoencoderModel:
    """
    Wrapper that handles training, inference, and score normalization.
    Keeps a running threshold from the training distribution so scores
    are calibrated relative to what the model considers 'normal'.
    """

    def __init__(self, input_dim: int = 12, threshold_percentile: float = 95.0):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = Autoencoder(input_dim).to(self.device)
        self.threshold_percentile = threshold_percentile
        self._threshold: float = 0.1  # default until calibrated
        self._fitted = False

    def fit(
        self,
        X: np.ndarray,
        epochs: int = 50,
        batch_size: int = 256,
        lr: float = 1e-3,
    ):
        """Train the autoencoder on normal traffic data."""
        logger.info("training autoencoder on %d samples for %d epochs", X.shape[0], epochs)
        self.model.train()
        tensor = torch.tensor(X, dtype=torch.float32).to(self.device)
        dataset = torch.utils.data.TensorDataset(tensor)
        loader = torch.utils.data.DataLoader(dataset, batch_size=batch_size, shuffle=True)

        optimizer = torch.optim.Adam(self.model.parameters(), lr=lr)
        criterion = nn.MSELoss()

        for epoch in range(epochs):
            total_loss = 0.0
            for (batch,) in loader:
                optimizer.zero_grad()
                output = self.model(batch)
                loss = criterion(output, batch)
                loss.backward()
                optimizer.step()
                total_loss += loss.item()

            if (epoch + 1) % 10 == 0:
                avg = total_loss / len(loader)
                logger.info("epoch %d/%d — avg loss: %.6f", epoch + 1, epochs, avg)

        # calibrate threshold from the training set's error distribution
        self.model.eval()
        with torch.no_grad():
            recon = self.model(tensor)
            errors = torch.mean((recon - tensor) ** 2, dim=1).cpu().numpy()
        self._threshold = float(np.percentile(errors, self.threshold_percentile))
        self._fitted = True
        logger.info("autoencoder trained — threshold (p%.0f): %.6f",
                     self.threshold_percentile, self._threshold)

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Return anomaly scores in [0, 1]."""
        if not self._fitted:
            return np.full(X.shape[0], 0.5)

        self.model.eval()
        tensor = torch.tensor(X, dtype=torch.float32).to(self.device)
        with torch.no_grad():
            recon = self.model(tensor)
            errors = torch.mean((recon - tensor) ** 2, dim=1).cpu().numpy()

        # normalize relative to the training threshold
        scores = errors / (self._threshold * 2 + 1e-8)
        return np.clip(scores, 0.0, 1.0)

    def predict_single(self, features: np.ndarray) -> float:
        return float(self.predict(features.reshape(1, -1))[0])

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save({
            "state_dict": self.model.state_dict(),
            "threshold": self._threshold,
            "fitted": self._fitted,
        }, path)
        logger.info("autoencoder saved to %s", path)

    def load(self, path: Path):
        if not path.exists():
            logger.warning("autoencoder checkpoint not found at %s", path)
            return
        ckpt = torch.load(path, map_location=self.device, weights_only=False)
        self.model.load_state_dict(ckpt["state_dict"])
        self._threshold = ckpt.get("threshold", 0.1)
        self._fitted = ckpt.get("fitted", True)
        logger.info("autoencoder loaded from %s (threshold=%.6f)", path, self._threshold)
