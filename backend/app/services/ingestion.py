"""Alert ingestion orchestration."""

from sqlalchemy.orm import Session

from app.domain.models import CloudWatchIngestResponse
from app.services.normalization import normalize_cloudwatch_payload
from app.services.service_registry import ServiceRegistry
from app.storage.repositories import IncidentRepository
from app.tasks import enqueue_triage
from app.utils.hashing import dedup_key_for


def ingest_cloudwatch_alert(db: Session, payload: dict) -> CloudWatchIngestResponse:
    """Normalize alert, upsert incident, enqueue triage."""

    event = normalize_cloudwatch_payload(payload)
    registry = ServiceRegistry()
    resolved = registry.resolve(event.resource_refs.get("alarm_name", ""))
    service = resolved["service"]
    env = resolved["env"]
    dedup_key = dedup_key_for(service, env, event.resource_refs.get("alarm_name", ""), event.labels)

    repo = IncidentRepository(db)
    alert_row = repo.create_alert_event(event)
    incident = repo.upsert_incident(dedup_key, service, env, alert_row.id)
    db.commit()

    enqueue_triage(str(incident.id))

    return CloudWatchIngestResponse(incident_id=incident.id, dedup_key=dedup_key, status=incident.status)
