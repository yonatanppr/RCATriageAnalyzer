"""FastAPI routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.domain.models import IncidentDetail, IncidentListItem, IncidentStatus
from app.services.ingestion import ingest_cloudwatch_alert
from app.storage.database import get_db
from app.storage.repositories import IncidentRepository

router = APIRouter(prefix="/v1")


@router.post("/alerts/cloudwatch")
def post_cloudwatch_alert(payload: dict, db: Session = Depends(get_db)):
    return ingest_cloudwatch_alert(db, payload)


@router.get("/incidents", response_model=list[IncidentListItem])
def list_incidents(db: Session = Depends(get_db)):
    repo = IncidentRepository(db)
    incidents = repo.list_incidents()
    return [
        IncidentListItem(
            id=i.id,
            dedup_key=i.dedup_key,
            service=i.service,
            env=i.env,
            status=i.status,
            created_at=i.created_at,
            updated_at=i.updated_at,
        )
        for i in incidents
    ]


@router.get("/incidents/{incident_id}", response_model=IncidentDetail)
def get_incident(incident_id: UUID, db: Session = Depends(get_db)):
    repo = IncidentRepository(db)
    incident = repo.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="incident not found")
    alert = repo.get_latest_alert_event(incident)
    return IncidentDetail(
        id=incident.id,
        dedup_key=incident.dedup_key,
        service=incident.service,
        env=incident.env,
        status=incident.status,
        created_at=incident.created_at,
        updated_at=incident.updated_at,
        latest_alert_event_id=incident.latest_alert_event_id,
        alert_title=alert.title if alert else None,
        alert_fired_at=alert.fired_at if alert else None,
        last_error=incident.last_error,
    )


@router.get("/incidents/{incident_id}/evidence")
def get_incident_evidence(incident_id: UUID, db: Session = Depends(get_db)):
    repo = IncidentRepository(db)
    evidence = repo.get_latest_evidence_pack(incident_id)
    if not evidence:
        return None
    return {
        "id": evidence.id,
        "incident_id": evidence.incident_id,
        "time_window_start": evidence.time_window_start,
        "time_window_end": evidence.time_window_end,
        "artifacts": evidence.artifacts,
        "provenance": evidence.provenance,
    }


@router.get("/incidents/{incident_id}/report")
def get_incident_report(incident_id: UUID, db: Session = Depends(get_db)):
    repo = IncidentRepository(db)
    report = repo.get_triage_report(incident_id)
    if not report:
        incident = repo.get_incident(incident_id)
        if incident and incident.status == IncidentStatus.failed:
            return {
                "status": "failed",
                "reason": incident.last_error,
                "message": "LLM unavailable or not configured",
            }
        return None
    return {
        "id": report.id,
        "incident_id": report.incident_id,
        "generated_at": report.generated_at,
        "model": report.model,
        **report.payload,
    }
