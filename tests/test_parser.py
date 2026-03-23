"""Tests for the log parser module."""

import pytest
from app.services.log_parser import parse_log


class TestParseStructuredJSON:
    """Test parsing of structured JSON log events."""

    def test_basic_http_event(self):
        raw = {
            "timestamp": "2024-01-15T10:30:00+00:00",
            "source_ip": "192.168.1.10",
            "dest_ip": "10.0.0.1",
            "method": "GET",
            "path": "/api/users",
            "status_code": 200,
            "user_agent": "Mozilla/5.0",
            "log_source": "http",
            "raw_log": '{"test": true}',
        }
        result = parse_log(raw)
        assert result is not None
        assert result["source_ip"] == "192.168.1.10"
        assert result["method"] == "GET"
        assert result["status_code"] == 200
        assert result["log_source"] == "http"

    def test_ssh_event(self):
        raw = {
            "timestamp": "2024-01-15T10:30:00+00:00",
            "source_ip": "10.0.0.99",
            "method": "SSH",
            "path": "/ssh/auth",
            "status_code": 401,
            "log_source": "ssh",
            "raw_log": "{}",
        }
        result = parse_log(raw)
        assert result is not None
        assert result["status_code"] == 401
        assert result["log_source"] == "ssh"

    def test_missing_fields_get_defaults(self):
        raw = {"raw_log": "minimal event"}
        result = parse_log(raw)
        assert result is not None
        assert result["source_ip"] == "0.0.0.0"
        assert result["method"] == "UNKNOWN"

    def test_json_string_input(self):
        import json
        raw = json.dumps({
            "timestamp": "2024-01-15T10:30:00+00:00",
            "source_ip": "172.16.0.5",
            "method": "POST",
            "path": "/api/login",
            "status_code": 401,
            "raw_log": "test",
        })
        result = parse_log(raw)
        assert result is not None
        assert result["source_ip"] == "172.16.0.5"


class TestParseTextLogs:
    """Test regex-based parsing of plain text log formats."""

    def test_apache_combined_log(self):
        line = '192.168.1.20 - - [15/Jan/2024:10:30:00 +0000] "GET /index.html HTTP/1.1" 200 1234'
        result = parse_log(line)
        assert result is not None
        assert result["source_ip"] == "192.168.1.20"
        assert result["method"] == "GET"
        assert result["path"] == "/index.html"
        assert result["status_code"] == 200

    def test_unparseable_text(self):
        result = parse_log("random gibberish that matches nothing")
        assert result is None


class TestEdgeCases:
    def test_none_returns_none(self):
        result = parse_log(42)  # not a dict or string
        assert result is None

    def test_bad_timestamp(self):
        raw = {
            "timestamp": "not-a-date",
            "source_ip": "1.2.3.4",
            "raw_log": "{}",
        }
        result = parse_log(raw)
        assert result is not None
        # should fall back to current time
        assert result["timestamp"] is not None
