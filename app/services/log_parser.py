"""
Log parser and normalizer.
Accepts raw log dicts and extracts a common schema.
Handles structured JSON logs and falls back to regex for plain-text formats.
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("soc.parser")

# common log format regex (Apache/Nginx combined)
CLF_PATTERN = re.compile(
    r'(?P<ip>[\d.]+)\s+-\s+-\s+\[(?P<ts>[^\]]+)\]\s+'
    r'"(?P<method>\w+)\s+(?P<path>\S+)\s+HTTP/[\d.]+"\s+'
    r'(?P<status>\d+)\s+(?P<size>\d+)'
)

# syslog-style auth log
AUTH_PATTERN = re.compile(
    r'(?P<ts>\w+\s+\d+\s+[\d:]+)\s+\S+\s+sshd\[\d+\]:\s+'
    r'(?P<result>Accepted|Failed)\s+\w+\s+for\s+\S+\s+from\s+(?P<ip>[\d.]+)'
)


def parse_log(raw: dict | str) -> Optional[dict]:
    """
    Normalize a raw log entry into the pipeline's common schema.
    Returns None if parsing fails entirely.
    """
    # if it's a string, try to decode as JSON first
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return _parse_text(raw)

    # structured JSON from our fake generator or real API gateways
    if isinstance(raw, dict):
        return _normalize_dict(raw)

    logger.warning("unparseable log type: %s", type(raw))
    return None


def _normalize_dict(data: dict) -> dict:
    """Normalize a structured dict to the common schema."""
    ts_raw = data.get("timestamp", "")
    try:
        ts = datetime.fromisoformat(ts_raw) if ts_raw else datetime.now(timezone.utc)
    except (ValueError, TypeError):
        ts = datetime.now(timezone.utc)

    return {
        "timestamp": ts.isoformat(),
        "source_ip": data.get("source_ip", data.get("src_ip", "0.0.0.0")),
        "dest_ip": data.get("dest_ip", data.get("dst_ip")),
        "method": data.get("method", "UNKNOWN"),
        "path": data.get("path", data.get("url", "/")),
        "status_code": _safe_int(data.get("status_code", data.get("status"))),
        "user_agent": data.get("user_agent", ""),
        "log_source": data.get("log_source", "unknown"),
        "raw_log": data.get("raw_log", json.dumps(data)),
    }


def _parse_text(text: str) -> Optional[dict]:
    """Attempt regex parsing for common text log formats."""
    # try combined log format
    m = CLF_PATTERN.search(text)
    if m:
        return {
            "timestamp": _parse_clf_time(m.group("ts")),
            "source_ip": m.group("ip"),
            "dest_ip": None,
            "method": m.group("method"),
            "path": m.group("path"),
            "status_code": int(m.group("status")),
            "user_agent": "",
            "log_source": "http",
            "raw_log": text,
        }

    # try auth log
    m = AUTH_PATTERN.search(text)
    if m:
        status = 200 if m.group("result") == "Accepted" else 401
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_ip": m.group("ip"),
            "dest_ip": None,
            "method": "SSH",
            "path": "/ssh/auth",
            "status_code": status,
            "user_agent": "sshd",
            "log_source": "ssh",
            "raw_log": text,
        }

    logger.debug("no regex matched for text log: %.80s", text)
    return None


def _parse_clf_time(ts: str) -> str:
    """Parse Apache/Nginx timestamp format."""
    try:
        dt = datetime.strptime(ts, "%d/%b/%Y:%H:%M:%S %z")
        return dt.isoformat()
    except ValueError:
        return datetime.now(timezone.utc).isoformat()


def _safe_int(val) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None
