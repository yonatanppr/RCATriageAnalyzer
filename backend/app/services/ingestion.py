"""Alert ingestion orchestration."""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.domain.models import CloudWatchIngestResponse
from app.services.normalization import normalize_alertmanager_payload, normalize_cloudwatch_payload
from app.services.service_registry import ServiceRegistry
from app.storage.repositories import IncidentRepository
from app.tasks import enqueue_triage
from app.utils.hashing import dedup_key_for


def ingest_cloudwatch_alert(db: Session, payload: dict) -> CloudWatchIngestResponse:
    """Normalize alert, upsert incident, enqueue triage."""

    event = normalize_cloudwatch_payload(payload)
    return _ingest_normalized_event(
        db=db,
        event=event,
        service_lookup_key=event.resource_refs.get("alarm_name", ""),
    )


def ingest_alertmanager_alert(db: Session, payload: dict) -> CloudWatchIngestResponse:
    event = normalize_alertmanager_payload(payload)
    service_key = event.resource_refs.get("service", "")
    return _ingest_normalized_event(
        db=db,
        event=event,
        service_lookup_key=service_key,
    )


def _ingest_normalized_event(db: Session, event, service_lookup_key: str) -> CloudWatchIngestResponse:
    registry = ServiceRegistry()
    resolved = registry.resolve(service_lookup_key)
    service = resolved["service"]
    env = resolved["env"]
    dedup_key = dedup_key_for(
        service,
        env,
        service_lookup_key,
        event.labels,
        event.correlation_id,
    )

    repo = IncidentRepository(db)
    alert_row = repo.create_alert_event(event)
    incident = repo.upsert_incident(dedup_key, service, env, alert_row.id, event.correlation_id)

    deploy_window_start = event.fired_at - timedelta(minutes=90)
    recent_deploys = repo.list_recent_deployments(
        service=service,
        env=env,
        since=deploy_window_start,
        until=event.fired_at,
    )
    if recent_deploys:
        latest = recent_deploys[0]
        repo.attach_incident_version(incident, latest.version, latest.git_sha)

    db.commit()

    enqueue_triage(str(incident.id))

    return CloudWatchIngestResponse(incident_id=incident.id, dedup_key=dedup_key, status=incident.status)
