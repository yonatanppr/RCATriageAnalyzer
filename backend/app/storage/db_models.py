"""SQLAlchemy models for persistence."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.domain.models import IncidentStatus
from app.storage.database import Base


def json_type():
    """Use JSONB on postgres and JSON elsewhere."""

    return JSON().with_variant(JSONB, "postgresql")


class AlertEventORM(Base):
    __tablename__ = "alert_events"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    severity: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    labels: Mapped[dict] = mapped_column(json_type(), nullable=False, default=dict)
    annotations: Mapped[dict] = mapped_column(json_type(), nullable=False, default=dict)
    resource_refs: Mapped[dict] = mapped_column(json_type(), nullable=False, default=dict)
    raw_payload: Mapped[dict] = mapped_column(json_type(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class IncidentORM(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    dedup_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    service: Mapped[str] = mapped_column(String(255), nullable=False)
    env: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[IncidentStatus] = mapped_column(Enum(IncidentStatus), default=IncidentStatus.open, nullable=False)
    latest_alert_event_id: Mapped[str | None] = mapped_column(UUID(as_uuid=True), ForeignKey("alert_events.id"), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class EvidencePackORM(Base):
    __tablename__ = "evidence_packs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    incident_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("incidents.id"), nullable=False, index=True)
    time_window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    time_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    artifacts: Mapped[list] = mapped_column(json_type(), nullable=False)
    provenance: Mapped[dict] = mapped_column(json_type(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class TriageReportORM(Base):
    __tablename__ = "triage_reports"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    incident_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("incidents.id"), nullable=False, unique=True, index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict] = mapped_column(json_type(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
