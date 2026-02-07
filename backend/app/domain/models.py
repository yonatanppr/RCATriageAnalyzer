"""Domain schemas and enums."""

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class IncidentStatus(str, Enum):
    """Incident lifecycle status."""

    open = "open"
    triaging = "triaging"
    triaged = "triaged"
    failed = "failed"


class AlertEvent(BaseModel):
    """Canonical alert event."""

    source: Literal["cloudwatch"]
    external_id: str
    title: str
    severity: str
    state: str
    fired_at: datetime
    ended_at: datetime | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    resource_refs: dict[str, str] = Field(default_factory=dict)
    raw_payload: dict[str, Any]


class EvidenceCitation(BaseModel):
    """Evidence citation entry."""

    kind: Literal["logs_pattern", "logs_query", "repo_snippet"]
    ref_id: str


class Symptom(BaseModel):
    text: str
    citations: list[EvidenceCitation]


class Hypothesis(BaseModel):
    rank: int
    title: str
    explanation: str
    confidence: float
    citations: list[EvidenceCitation]

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("confidence must be between 0 and 1")
        return value


class VerificationStep(BaseModel):
    step: str
    command_or_query: str | None = None
    citations: list[EvidenceCitation]


class Mitigation(BaseModel):
    action: str
    risk: str
    citations: list[EvidenceCitation]


class TriageReportPayload(BaseModel):
    """Strict report schema expected from the LLM."""

    summary: str
    symptoms: list[Symptom]
    hypotheses: list[Hypothesis]
    verification_steps: list[VerificationStep]
    mitigations: list[Mitigation]
    notes: str | None = None

    @field_validator("hypotheses")
    @classmethod
    def ensure_hypotheses_have_citations(cls, hypotheses: list[Hypothesis]) -> list[Hypothesis]:
        for hypothesis in hypotheses:
            if not hypothesis.citations:
                raise ValueError("every hypothesis must include at least one citation")
        return hypotheses


class EvidencePack(BaseModel):
    """Stored evidence artifact."""

    id: UUID
    incident_id: UUID
    time_window_start: datetime
    time_window_end: datetime
    artifacts: list[dict[str, Any]]
    provenance: dict[str, Any]


class IncidentListItem(BaseModel):
    id: UUID
    dedup_key: str
    service: str
    env: str
    status: IncidentStatus
    created_at: datetime
    updated_at: datetime


class IncidentDetail(IncidentListItem):
    latest_alert_event_id: UUID | None = None
    alert_title: str | None = None
    alert_fired_at: datetime | None = None
    last_error: str | None = None


class CloudWatchIngestResponse(BaseModel):
    incident_id: UUID
    dedup_key: str
    status: IncidentStatus
