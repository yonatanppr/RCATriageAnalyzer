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
    awaiting_human_review = "awaiting_human_review"
    triaged = "triaged"
    mitigated = "mitigated"
    resolved = "resolved"
    postmortem_required = "postmortem_required"
    failed = "failed"


class IncidentDecision(str, Enum):
    approve = "approve"
    reject = "reject"


class IncidentStatusUpdate(str, Enum):
    mitigated = "mitigated"
    resolved = "resolved"
    postmortem_required = "postmortem_required"


class UserRole(str, Enum):
    viewer = "viewer"
    responder = "responder"
    admin = "admin"


class AlertEvent(BaseModel):
    """Canonical alert event."""

    source: Literal["cloudwatch", "alertmanager"]
    external_id: str
    title: str
    severity: str
    state: str
    correlation_id: str | None = None
    fired_at: datetime
    ended_at: datetime | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    resource_refs: dict[str, str] = Field(default_factory=dict)
    raw_payload: dict[str, Any]


class EvidenceRef(BaseModel):
    artifact_id: str
    pointer: str


class FactClaim(BaseModel):
    claim_id: str
    text: str
    evidence_refs: list[EvidenceRef]


class Hypothesis(BaseModel):
    rank: int
    title: str
    explanation: str
    confidence: float
    evidence_refs: list[EvidenceRef]
    disconfirming_signals: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("confidence must be between 0 and 1")
        return value


class NextCheck(BaseModel):
    check_id: str
    step: str
    command_or_query: str | None = None
    evidence_refs: list[EvidenceRef]


class MitigationAction(BaseModel):
    mitigation_id: str
    action: str
    risk: str
    evidence_refs: list[EvidenceRef]


class ReportClaim(BaseModel):
    claim_id: str
    type: Literal["fact", "hypothesis", "next_check", "mitigation"]
    text: str
    evidence_refs: list[EvidenceRef]


class TriageReportPayload(BaseModel):
    """Strict report schema expected from the LLM."""

    summary: str
    mode: Literal["normal", "insufficient_evidence"] = "normal"
    facts: list[FactClaim]
    hypotheses: list[Hypothesis]
    next_checks: list[NextCheck]
    mitigations: list[MitigationAction]
    claims: list[ReportClaim]
    uncertainty_note: str | None = None
    generation_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("facts")
    @classmethod
    def ensure_facts_have_citations(cls, facts: list[FactClaim]) -> list[FactClaim]:
        for fact in facts:
            if not fact.evidence_refs:
                raise ValueError("every fact must include at least one evidence_ref")
        return facts


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
    service_version: str | None = None
    git_sha: str | None = None
    correlation_id: str | None = None
    status: IncidentStatus
    created_at: datetime
    updated_at: datetime


class IncidentDetail(IncidentListItem):
    latest_alert_event_id: UUID | None = None
    alert_title: str | None = None
    alert_fired_at: datetime | None = None
    last_error: str | None = None
    owners: list[str] = Field(default_factory=list)
    runbook_url: str | None = None
    dashboard_url: str | None = None


class CloudWatchIngestResponse(BaseModel):
    incident_id: UUID
    dedup_key: str
    status: IncidentStatus


class IncidentDecisionRequest(BaseModel):
    decision: IncidentDecision
    notes: str | None = None


class IncidentStatusUpdateRequest(BaseModel):
    status: IncidentStatusUpdate
    notes: str | None = None


class IncidentFeedbackRequest(BaseModel):
    helpful: bool
    correct: bool | None = None
    final_rca: str | None = None
    notes: str | None = None


class DeploymentEventIngestRequest(BaseModel):
    service: str
    env: str
    deployed_at: datetime
    version: str | None = None
    git_sha: str | None = None
    actor: str | None = None
    source: str = "webhook"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConfigChangeIngestRequest(BaseModel):
    service: str
    env: str
    changed_at: datetime
    actor: str | None = None
    diff: dict[str, Any] = Field(default_factory=dict)
    source: str = "config-feed"


class CloudWatchAlarmState(BaseModel):
    value: str
    reason: str | None = None
    timestamp: str


class CloudWatchAlarmDetail(BaseModel):
    alarmName: str
    state: CloudWatchAlarmState
    previousState: dict[str, str] | None = None
    correlationId: str | None = None
    correlation_id: str | None = None
    requestId: str | None = None
    request_id: str | None = None
    traceId: str | None = None
    trace_id: str | None = None


class CloudWatchAlarmEnvelope(BaseModel):
    version: str | None = None
    id: str
    source: Literal["aws.cloudwatch"]
    account: str | None = None
    time: str
    region: str | None = None
    resources: list[str] | None = None
    detail: CloudWatchAlarmDetail
    correlationId: str | None = None
    correlation_id: str | None = None


class AlertmanagerEnvelope(BaseModel):
    version: str | None = None
    groupKey: str
    status: str
    commonLabels: dict[str, str] = Field(default_factory=dict)
    commonAnnotations: dict[str, str] = Field(default_factory=dict)
    alerts: list[dict[str, Any]] = Field(default_factory=list)


class AuthPrincipal(BaseModel):
    subject: str
    role: UserRole
    services: list[str] = Field(default_factory=list)
    can_ingest: bool = False
