"""
ORM models for the SOC database.
Three core tables: events, alerts, and ip_reputation.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.database import Base


class Event(Base):
    """Every log entry that passes through the scoring pipeline."""

    __tablename__ = "events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp = Column(DateTime, nullable=False, index=True)
    source_ip = Column(String(45), nullable=False, index=True)  # IPv6 max len
    dest_ip = Column(String(45), nullable=True)
    method = Column(String(10), nullable=True)
    path = Column(String(2048), nullable=True)
    status_code = Column(Integer, nullable=True)
    user_agent = Column(String(512), nullable=True)
    raw_log = Column(Text, nullable=False)
    log_source = Column(String(32), nullable=True)  # http, ssh, api

    # ML scoring results
    anomaly_score = Column(Float, nullable=True)
    attack_type = Column(String(64), nullable=True)
    label = Column(String(32), nullable=True)  # for feedback loop: normal / attack / false_positive

    created_at = Column(DateTime, default=datetime.utcnow)

    alerts = relationship("Alert", back_populates="event", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_events_ip_time", "source_ip", "timestamp"),
    )


class Alert(Base):
    """Fired when an event's anomaly score exceeds the configured threshold."""

    __tablename__ = "alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(UUID(as_uuid=True), ForeignKey("events.id"), nullable=False)
    severity = Column(String(16), nullable=False, default="medium")  # low, medium, high, critical
    alert_type = Column(String(64), nullable=False)  # brute_force, ddos, anomaly, suspicious_api
    message = Column(Text, nullable=True)

    resolved = Column(Boolean, default=False)
    resolved_by = Column(String(128), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    is_false_positive = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    event = relationship("Event", back_populates="alerts")

    __table_args__ = (
        Index("ix_alerts_severity", "severity"),
        Index("ix_alerts_unresolved", "resolved", "created_at"),
    )


class IPReputation(Base):
    """Tracks cumulative reputation for each observed IP address."""

    __tablename__ = "ip_reputation"

    ip = Column(String(45), primary_key=True)
    total_events = Column(Integer, default=0)
    total_alerts = Column(Integer, default=0)
    anomaly_sum = Column(Float, default=0.0)
    reputation_score = Column(Float, default=0.5)  # 0.0 = blocked, 1.0 = trusted
    tag = Column(String(32), default="unknown")  # trusted, suspicious, blocked, unknown

    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
