"""Repository utilities."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.domain.models import AlertEvent, IncidentStatus, TriageReportPayload
from app.storage.db_models import AlertEventORM, EvidencePackORM, IncidentORM, TriageReportORM


class IncidentRepository:
    """DB operations for incidents and artifacts."""

    def __init__(self, db: Session):
        self.db = db

    def create_alert_event(self, event: AlertEvent) -> AlertEventORM:
        row = AlertEventORM(**event.model_dump())
        self.db.add(row)
        self.db.flush()
        return row

    def upsert_incident(self, dedup_key: str, service: str, env: str, alert_event_id: UUID) -> IncidentORM:
        stmt = select(IncidentORM).where(IncidentORM.dedup_key == dedup_key)
        incident = self.db.execute(stmt).scalar_one_or_none()
        if incident is None:
            incident = IncidentORM(
                dedup_key=dedup_key,
                service=service,
                env=env,
                status=IncidentStatus.open,
                latest_alert_event_id=alert_event_id,
            )
            self.db.add(incident)
        else:
            incident.latest_alert_event_id = alert_event_id
            if incident.status == IncidentStatus.failed:
                incident.status = IncidentStatus.open
                incident.last_error = None
        self.db.flush()
        return incident

    def get_incident(self, incident_id: UUID) -> IncidentORM | None:
        return self.db.get(IncidentORM, incident_id)

    def list_incidents(self) -> list[IncidentORM]:
        stmt = select(IncidentORM).order_by(desc(IncidentORM.updated_at))
        return list(self.db.execute(stmt).scalars())

    def set_incident_status(self, incident: IncidentORM, status: IncidentStatus, error: str | None = None) -> None:
        incident.status = status
        incident.last_error = error
        incident.updated_at = datetime.utcnow()
        self.db.flush()

    def get_latest_alert_event(self, incident: IncidentORM) -> AlertEventORM | None:
        if not incident.latest_alert_event_id:
            return None
        return self.db.get(AlertEventORM, incident.latest_alert_event_id)

    def store_evidence_pack(
        self,
        incident_id: UUID,
        time_window_start: datetime,
        time_window_end: datetime,
        artifacts: list[dict],
        provenance: dict,
    ) -> EvidencePackORM:
        row = EvidencePackORM(
            incident_id=incident_id,
            time_window_start=time_window_start,
            time_window_end=time_window_end,
            artifacts=artifacts,
            provenance=provenance,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def get_latest_evidence_pack(self, incident_id: UUID) -> EvidencePackORM | None:
        stmt = (
            select(EvidencePackORM)
            .where(EvidencePackORM.incident_id == incident_id)
            .order_by(desc(EvidencePackORM.created_at))
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def store_triage_report(self, incident_id: UUID, model_name: str, payload: TriageReportPayload) -> TriageReportORM:
        existing_stmt = select(TriageReportORM).where(TriageReportORM.incident_id == incident_id)
        existing = self.db.execute(existing_stmt).scalar_one_or_none()
        if existing:
            existing.generated_at = datetime.utcnow()
            existing.model = model_name
            existing.payload = payload.model_dump()
            self.db.flush()
            return existing

        row = TriageReportORM(
            incident_id=incident_id,
            generated_at=datetime.utcnow(),
            model=model_name,
            payload=payload.model_dump(),
        )
        self.db.add(row)
        self.db.flush()
        return row

    def get_triage_report(self, incident_id: UUID) -> TriageReportORM | None:
        stmt = select(TriageReportORM).where(TriageReportORM.incident_id == incident_id)
        return self.db.execute(stmt).scalar_one_or_none()
