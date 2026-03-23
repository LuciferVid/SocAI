"""
Pydantic v2 schemas for API request/response serialization.
Kept separate from ORM models to maintain clean boundaries.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ---------- Event schemas ----------

class EventBase(BaseModel):
    timestamp: datetime
    source_ip: str
    dest_ip: Optional[str] = None
    method: Optional[str] = None
    path: Optional[str] = None
    status_code: Optional[int] = None
    user_agent: Optional[str] = None
    raw_log: str
    log_source: Optional[str] = None


class EventOut(EventBase):
    id: UUID
    anomaly_score: Optional[float] = None
    attack_type: Optional[str] = None
    label: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class EventScored(BaseModel):
    """Internal schema passed through the pipeline after scoring."""
    event: EventBase
    anomaly_score: float
    attack_type: Optional[str] = None
    features: dict = Field(default_factory=dict)


class EventLabelUpdate(BaseModel):
    label: str = Field(..., pattern="^(normal|attack|false_positive)$")


# ---------- Alert schemas ----------

class AlertOut(BaseModel):
    id: UUID
    event_id: UUID
    severity: str
    alert_type: str
    message: Optional[str] = None
    resolved: bool
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    is_false_positive: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AlertResolve(BaseModel):
    resolved_by: str = "analyst"
    is_false_positive: bool = False


# ---------- IP Reputation schemas ----------

class IPReputationOut(BaseModel):
    ip: str
    total_events: int
    total_alerts: int
    anomaly_sum: float
    reputation_score: float
    tag: str
    first_seen: datetime
    last_seen: datetime

    model_config = {"from_attributes": True}


class IPTagUpdate(BaseModel):
    tag: str = Field(..., pattern="^(trusted|suspicious|blocked|unknown)$")


# ---------- Dashboard / WebSocket schemas ----------

class LiveEvent(BaseModel):
    """Payload pushed to dashboard via WebSocket."""
    event_id: str
    timestamp: str
    source_ip: str
    method: Optional[str] = None
    path: Optional[str] = None
    status_code: Optional[int] = None
    anomaly_score: float
    attack_type: Optional[str] = None
    severity: Optional[str] = None


# ---------- Stats / Misc ----------

class PipelineStats(BaseModel):
    total_events: int
    total_alerts: int
    active_alerts: int
    blocked_ips: int
    avg_anomaly_score: float
    model_version: Optional[str] = None
