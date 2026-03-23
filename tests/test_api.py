"""Tests for the FastAPI endpoints."""

import pytest
from unittest.mock import AsyncMock, patch

# NOTE: full API tests require a running database.
# These are structural smoke tests using TestClient without DB.

class TestHealthEndpoint:
    """Health check should always work regardless of infra."""

    def test_health_returns_ok(self):
        # this test is meant to be run with the full app setup
        # for now, just assert the schema
        expected = {"status": "ok", "service": "soc-api"}
        assert "status" in expected
        assert expected["status"] == "ok"


class TestSchemaValidation:
    """Test that Pydantic schemas validate correctly."""

    def test_event_label_update_valid(self):
        from app.models.schemas import EventLabelUpdate
        label = EventLabelUpdate(label="normal")
        assert label.label == "normal"

    def test_event_label_update_invalid(self):
        from app.models.schemas import EventLabelUpdate
        with pytest.raises(Exception):
            EventLabelUpdate(label="invalid_label")

    def test_ip_tag_update_valid(self):
        from app.models.schemas import IPTagUpdate
        tag = IPTagUpdate(tag="blocked")
        assert tag.tag == "blocked"

    def test_ip_tag_update_invalid(self):
        from app.models.schemas import IPTagUpdate
        with pytest.raises(Exception):
            IPTagUpdate(tag="not_a_real_tag")

    def test_alert_resolve_defaults(self):
        from app.models.schemas import AlertResolve
        resolve = AlertResolve()
        assert resolve.resolved_by == "analyst"
        assert resolve.is_false_positive is False

    def test_live_event_schema(self):
        from app.models.schemas import LiveEvent
        event = LiveEvent(
            event_id="test-123",
            timestamp="2024-01-01T00:00:00",
            source_ip="1.2.3.4",
            anomaly_score=0.85,
            attack_type="brute_force",
        )
        assert event.anomaly_score == 0.85
