"""FastAPI routes."""

from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.domain.models import (
    AuthPrincipal,
    ConfigChangeIngestRequest,
    CloudWatchAlarmEnvelope,
    DeploymentEventIngestRequest,
    AlertmanagerEnvelope,
    IncidentDecision,
    IncidentDecisionRequest,
    IncidentDetail,
    IncidentFeedbackRequest,
    IncidentListItem,
    IncidentStatus,
    IncidentStatusUpdate,
    IncidentStatusUpdateRequest,
    UserRole,
)
from app.services.ingestion import ingest_alertmanager_alert, ingest_cloudwatch_alert
from app.services.security import authorize_service, require_auth, require_ingest
from app.services.service_registry import ServiceRegistry
from app.storage.database import get_db
from app.storage.repositories import IncidentRepository

router = APIRouter(prefix="/v1")


@router.post("/alerts/cloudwatch")
def post_cloudwatch_alert(
    payload: CloudWatchAlarmEnvelope,
    db: Session = Depends(get_db),
    principal: Annotated[AuthPrincipal, Depends(require_auth)] = None,
):
    require_ingest(principal)
    return ingest_cloudwatch_alert(db, payload.model_dump())


@router.post("/alerts/alertmanager")
def post_alertmanager_alert(
    payload: AlertmanagerEnvelope,
    db: Session = Depends(get_db),
    principal: Annotated[AuthPrincipal, Depends(require_auth)] = None,
):
    require_ingest(principal)
    return ingest_alertmanager_alert(db, payload.model_dump())


@router.get("/incidents", response_model=list[IncidentListItem])
def list_incidents(
    db: Session = Depends(get_db),
    principal: Annotated[AuthPrincipal, Depends(require_auth)] = None,
):
    repo = IncidentRepository(db)
    incidents = repo.list_incidents()
    visible = []
    for incident in incidents:
        try:
            authorize_service(principal, incident.service)
        except HTTPException:
            continue
        visible.append(incident)
    repo.create_audit_log(
        actor=principal.subject,
        action="incidents.list",
        resource_type="incident",
        resource_id=None,
        details={"returned": len(visible)},
    )
    db.commit()
    return [
        IncidentListItem(
            id=i.id,
            dedup_key=i.dedup_key,
            service=i.service,
            env=i.env,
            service_version=i.service_version,
            git_sha=i.git_sha,
            correlation_id=i.correlation_id,
            status=i.status,
            created_at=i.created_at,
            updated_at=i.updated_at,
        )
        for i in visible
    ]


@router.get("/incidents/{incident_id}", response_model=IncidentDetail)
def get_incident(
    incident_id: UUID,
    db: Session = Depends(get_db),
    principal: Annotated[AuthPrincipal, Depends(require_auth)] = None,
):
    repo = IncidentRepository(db)
    incident = repo.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="incident not found")
    authorize_service(principal, incident.service)
    alert = repo.get_latest_alert_event(incident)
    registry = ServiceRegistry().resolve(incident.service)
    repo.create_audit_log(
        actor=principal.subject,
        action="incident.read",
        resource_type="incident",
        resource_id=str(incident.id),
        details={},
    )
    db.commit()
    return IncidentDetail(
        id=incident.id,
        dedup_key=incident.dedup_key,
        service=incident.service,
        env=incident.env,
        service_version=incident.service_version,
        git_sha=incident.git_sha,
        correlation_id=incident.correlation_id,
        status=incident.status,
        created_at=incident.created_at,
        updated_at=incident.updated_at,
        latest_alert_event_id=incident.latest_alert_event_id,
        alert_title=alert.title if alert else None,
        alert_fired_at=alert.fired_at if alert else None,
        last_error=incident.last_error,
        owners=registry.get("owners", []),
        runbook_url=registry.get("runbook_url"),
        dashboard_url=registry.get("dashboard_url"),
    )


@router.get("/incidents/{incident_id}/evidence")
def get_incident_evidence(
    incident_id: UUID,
    db: Session = Depends(get_db),
    principal: Annotated[AuthPrincipal, Depends(require_auth)] = None,
):
    repo = IncidentRepository(db)
    incident = repo.get_incident(incident_id)
    if not incident:
        return None
    authorize_service(principal, incident.service)
    evidence = repo.get_latest_evidence_pack(incident_id)
    if not evidence:
        return None
    repo.create_audit_log(
        actor=principal.subject,
        action="evidence.read",
        resource_type="evidence_pack",
        resource_id=str(evidence.id),
        details={},
    )
    db.commit()
    return {
        "id": evidence.id,
        "incident_id": evidence.incident_id,
        "time_window_start": evidence.time_window_start,
        "time_window_end": evidence.time_window_end,
        "artifacts": evidence.artifacts,
        "provenance": evidence.provenance,
    }


@router.get("/incidents/{incident_id}/report")
def get_incident_report(
    incident_id: UUID,
    db: Session = Depends(get_db),
    principal: Annotated[AuthPrincipal, Depends(require_auth)] = None,
):
    repo = IncidentRepository(db)
    incident = repo.get_incident(incident_id)
    if incident:
        authorize_service(principal, incident.service)
    report = repo.get_triage_report(incident_id)
    if not report:
        if incident and incident.status == IncidentStatus.failed:
            return {
                "status": "failed",
                "reason": incident.last_error,
                "message": "LLM unavailable or not configured",
            }
        return None
    review_required = bool(incident and incident.status == IncidentStatus.awaiting_human_review)
    repo.create_audit_log(
        actor=principal.subject,
        action="report.read",
        resource_type="triage_report",
        resource_id=str(report.id),
        details={},
    )
    db.commit()
    return {
        "id": report.id,
        "incident_id": report.incident_id,
        "generated_at": report.generated_at,
        "model": report.model,
        "decision_required": review_required,
        "status": incident.status if incident else None,
        **report.payload,
    }


@router.post("/incidents/{incident_id}/decision")
def decide_incident_report(
    incident_id: UUID,
    payload: IncidentDecisionRequest,
    db: Session = Depends(get_db),
    principal: Annotated[AuthPrincipal, Depends(require_auth)] = None,
):
    repo = IncidentRepository(db)
    incident = repo.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="incident not found")
    authorize_service(principal, incident.service)
    if incident.status != IncidentStatus.awaiting_human_review:
        raise HTTPException(status_code=409, detail="incident is not awaiting human review")

    if payload.decision == IncidentDecision.approve:
        repo.set_incident_status(incident, IncidentStatus.triaged, None)
    else:
        repo.set_incident_status(incident, IncidentStatus.open, payload.notes or "report rejected by reviewer")
    repo.create_review_decision(incident_id, payload.decision.value, payload.notes)
    repo.create_audit_log(
        actor=principal.subject,
        action="report.decision",
        resource_type="incident",
        resource_id=str(incident.id),
        details={"decision": payload.decision.value},
    )
    db.commit()
    return {
        "incident_id": incident.id,
        "status": incident.status,
        "last_error": incident.last_error,
    }


@router.post("/incidents/{incident_id}/status")
def update_incident_status(
    incident_id: UUID,
    payload: IncidentStatusUpdateRequest,
    db: Session = Depends(get_db),
    principal: Annotated[AuthPrincipal, Depends(require_auth)] = None,
):
    repo = IncidentRepository(db)
    incident = repo.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="incident not found")
    authorize_service(principal, incident.service)

    allowed_from = {
        IncidentStatusUpdate.mitigated: {IncidentStatus.triaged},
        IncidentStatusUpdate.resolved: {IncidentStatus.triaged, IncidentStatus.mitigated},
        IncidentStatusUpdate.postmortem_required: {IncidentStatus.triaged, IncidentStatus.mitigated, IncidentStatus.resolved},
    }
    if incident.status not in allowed_from[payload.status]:
        raise HTTPException(status_code=409, detail=f"cannot transition from {incident.status} to {payload.status}")

    repo.set_incident_status(incident, IncidentStatus(payload.status.value), payload.notes)
    repo.create_audit_log(
        actor=principal.subject,
        action="incident.status.update",
        resource_type="incident",
        resource_id=str(incident.id),
        details={"status": payload.status.value},
    )
    db.commit()
    return {"incident_id": incident.id, "status": incident.status, "last_error": incident.last_error}


@router.get("/metrics/quality")
def quality_metrics(
    db: Session = Depends(get_db),
    principal: Annotated[AuthPrincipal, Depends(require_auth)] = None,
):
    repo = IncidentRepository(db)
    incidents = repo.list_incidents()
    review_counts = repo.count_review_decisions()
    total = len(incidents)
    status_counts: dict[str, int] = {}
    triage_latencies: list[float] = []
    for incident in incidents:
        key = incident.status.value
        status_counts[key] = status_counts.get(key, 0) + 1
        triage_latencies.append((incident.updated_at - incident.created_at).total_seconds())

    acceptance_rate = (
        review_counts["approve"] / (review_counts["approve"] + review_counts["reject"])
        if (review_counts["approve"] + review_counts["reject"]) > 0
        else 0.0
    )
    avg_triage_seconds = sum(triage_latencies) / len(triage_latencies) if triage_latencies else 0.0
    return {
        "total_incidents": total,
        "status_counts": status_counts,
        "review_decisions": review_counts,
        "review_acceptance_rate": round(acceptance_rate, 3),
        "avg_incident_lifecycle_seconds": round(avg_triage_seconds, 2),
    }


@router.get("/metrics/runtime")
def runtime_metrics(
    db: Session = Depends(get_db),
    principal: Annotated[AuthPrincipal, Depends(require_auth)] = None,
):
    _ = principal
    repo = IncidentRepository(db)
    return repo.runtime_metrics()


@router.post("/changes/deployments")
def ingest_deployment_change(
    payload: DeploymentEventIngestRequest,
    db: Session = Depends(get_db),
    principal: Annotated[AuthPrincipal, Depends(require_auth)] = None,
):
    require_ingest(principal)
    repo = IncidentRepository(db)
    row = repo.create_deployment_event(
        service=payload.service,
        env=payload.env,
        deployed_at=payload.deployed_at,
        version=payload.version,
        git_sha=payload.git_sha,
        actor=payload.actor,
        source=payload.source,
        meta=payload.metadata,
    )
    repo.create_audit_log(
        actor=principal.subject,
        action="deployment.ingest",
        resource_type="deployment_event",
        resource_id=str(row.id),
        details={"service": payload.service, "env": payload.env},
    )
    db.commit()
    return {"id": row.id, "service": row.service, "env": row.env}


@router.post("/changes/config")
def ingest_config_change(
    payload: ConfigChangeIngestRequest,
    db: Session = Depends(get_db),
    principal: Annotated[AuthPrincipal, Depends(require_auth)] = None,
):
    require_ingest(principal)
    repo = IncidentRepository(db)
    row = repo.create_config_change(
        service=payload.service,
        env=payload.env,
        changed_at=payload.changed_at,
        actor=payload.actor,
        diff=payload.diff,
        source=payload.source,
    )
    repo.create_audit_log(
        actor=principal.subject,
        action="config.ingest",
        resource_type="config_change",
        resource_id=str(row.id),
        details={"service": payload.service, "env": payload.env},
    )
    db.commit()
    return {"id": row.id, "service": row.service, "env": row.env}


@router.post("/incidents/{incident_id}/feedback")
def create_incident_feedback(
    incident_id: UUID,
    payload: IncidentFeedbackRequest,
    db: Session = Depends(get_db),
    principal: Annotated[AuthPrincipal, Depends(require_auth)] = None,
):
    repo = IncidentRepository(db)
    incident = repo.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="incident not found")
    authorize_service(principal, incident.service)
    row = repo.create_feedback(
        incident_id=incident_id,
        helpful=payload.helpful,
        correct=payload.correct,
        final_rca=payload.final_rca,
        notes=payload.notes,
    )
    repo.create_audit_log(
        actor=principal.subject,
        action="incident.feedback",
        resource_type="incident_feedback",
        resource_id=str(row.id),
        details={"helpful": payload.helpful, "correct": payload.correct},
    )
    db.commit()
    return {"id": row.id}


@router.get("/incidents/{incident_id}/feedback")
def list_incident_feedback(
    incident_id: UUID,
    db: Session = Depends(get_db),
    principal: Annotated[AuthPrincipal, Depends(require_auth)] = None,
):
    repo = IncidentRepository(db)
    incident = repo.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="incident not found")
    authorize_service(principal, incident.service)
    rows = repo.list_feedback(incident_id)
    repo.create_audit_log(
        actor=principal.subject,
        action="incident.feedback.read",
        resource_type="incident",
        resource_id=str(incident_id),
        details={"count": len(rows)},
    )
    db.commit()
    return [
        {
            "id": row.id,
            "helpful": row.helpful,
            "correct": row.correct,
            "final_rca": row.final_rca,
            "notes": row.notes,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.post("/admin/purge")
def purge_old_data(
    days: int = 30,
    db: Session = Depends(get_db),
    principal: Annotated[AuthPrincipal, Depends(require_auth)] = None,
):
    if principal.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="admin role required")
    repo = IncidentRepository(db)
    before = datetime.now(timezone.utc) - timedelta(days=days)
    result = repo.purge_old_data(before)
    repo.create_audit_log(
        actor=principal.subject,
        action="admin.purge",
        resource_type="system",
        resource_id=None,
        details={"days": days, **result},
    )
    db.commit()
    return result
