"""Tests for the ML scoring models."""

import numpy as np
import pytest

from app.ml.isolation_forest import IsolationForestModel
from app.ml.autoencoder import AutoencoderModel
from app.ml.hybrid import apply_rules, hybrid_score


class TestIsolationForest:

    def test_unfitted_returns_default(self):
        model = IsolationForestModel()
        X = np.random.randn(5, 12).astype(np.float32)
        scores = model.predict(X)
        assert scores.shape == (5,)
        assert all(s == 0.5 for s in scores)

    def test_fit_and_predict(self):
        model = IsolationForestModel(n_estimators=50)
        # normal data
        X_train = np.random.randn(200, 12).astype(np.float32)
        model.fit(X_train)

        scores = model.predict(X_train[:10])
        assert scores.shape == (10,)
        assert all(0.0 <= s <= 1.0 for s in scores)

    def test_single_prediction(self):
        model = IsolationForestModel(n_estimators=50)
        X_train = np.random.randn(200, 12).astype(np.float32)
        model.fit(X_train)

        score = model.predict_single(X_train[0])
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_save_and_load(self, tmp_path):
        model = IsolationForestModel(n_estimators=50)
        X = np.random.randn(100, 12).astype(np.float32)
        model.fit(X)
        path = tmp_path / "test_model.pkl"
        model.save(path)

        model2 = IsolationForestModel()
        model2.load(path)
        # loaded model should give same scores
        s1 = model.predict(X[:5])
        s2 = model2.predict(X[:5])
        np.testing.assert_array_almost_equal(s1, s2)


class TestAutoencoder:

    def test_unfitted_returns_default(self):
        model = AutoencoderModel(input_dim=12)
        X = np.random.randn(5, 12).astype(np.float32)
        scores = model.predict(X)
        assert all(s == 0.5 for s in scores)

    def test_fit_and_predict(self):
        model = AutoencoderModel(input_dim=12)
        X_train = np.random.randn(200, 12).astype(np.float32)
        model.fit(X_train, epochs=5, batch_size=64)

        scores = model.predict(X_train[:10])
        assert scores.shape == (10,)
        assert all(0.0 <= s <= 1.0 for s in scores)

    def test_save_and_load(self, tmp_path):
        model = AutoencoderModel(input_dim=12)
        X = np.random.randn(100, 12).astype(np.float32)
        model.fit(X, epochs=3)
        path = tmp_path / "test_ae.pt"
        model.save(path)

        model2 = AutoencoderModel(input_dim=12)
        model2.load(path)
        assert model2._fitted is True


class TestHybridRules:

    def test_brute_force_detection(self):
        features = np.zeros(12, dtype=np.float32)
        features[2] = 15   # ip_fail_count_1m
        features[7] = 1.0  # is_auth
        event = {"path": "/api/auth/login", "status_code": 401}

        rule_score, attack_type = apply_rules(features, event)
        assert rule_score == 1.0
        assert attack_type == "brute_force"

    def test_ddos_detection(self):
        features = np.zeros(12, dtype=np.float32)
        features[11] = 50.0  # burst_rate
        event = {"path": "/api/users", "status_code": 200}

        rule_score, attack_type = apply_rules(features, event)
        assert rule_score == 1.0
        assert attack_type == "ddos_spike"

    def test_suspicious_path(self):
        features = np.zeros(12, dtype=np.float32)
        event = {"path": "/admin/shell.php", "status_code": 404}

        rule_score, attack_type = apply_rules(features, event)
        assert rule_score == 0.8
        assert attack_type == "suspicious_api"

    def test_normal_traffic_no_rules(self):
        features = np.zeros(12, dtype=np.float32)
        features[0] = 3  # low request count
        event = {"path": "/api/users", "status_code": 200}

        rule_score, attack_type = apply_rules(features, event)
        assert rule_score == 0.0
        assert attack_type is None

    def test_hybrid_score_with_rule(self):
        features = np.zeros(12, dtype=np.float32)
        features[2] = 15
        features[7] = 1.0
        event = {"path": "/api/auth/login", "status_code": 401}

        score, attack_type = hybrid_score(0.3, features, event)
        assert score >= 0.7  # rule should boost even low ML score
        assert attack_type == "brute_force"
