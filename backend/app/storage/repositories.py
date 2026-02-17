"""Repository utilities."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, desc, func, select
from sqlalchemy.orm import Session

from app.domain.models import AlertEvent, IncidentStatus, TriageReportPayload
from app.storage.db_models import (
    AlertEventORM,
    AuditLogORM,
    ConfigChangeORM,
    DeploymentEventORM,
    EvidencePackORM,
    IncidentFeedbackORM,
    IncidentORM,
    PipelineRunORM,
    ReviewDecisionORM,
    TriageReportORM,
)


class IncidentRepository:
    """DB operations for incidents and artifacts."""

    def __init__(self, db: Session):
        self.db = db

    def create_alert_event(self, event: AlertEvent) -> AlertEventORM:
        row = AlertEventORM(**event.model_dump())
        self.db.add(row)
        self.db.flush()
        return row

    def upsert_incident(
        self,
        dedup_key: str,
        service: str,
        env: str,
        alert_event_id: UUID,
        correlation_id: str | None = None,
    ) -> IncidentORM:
        stmt = select(IncidentORM).where(IncidentORM.dedup_key == dedup_key)
        incident = self.db.execute(stmt).scalar_one_or_none()
        if incident is None:
            incident = IncidentORM(
                dedup_key=dedup_key,
                service=service,
                env=env,
                correlation_id=correlation_id,
                status=IncidentStatus.open,
                latest_alert_event_id=alert_event_id,
            )
            self.db.add(incident)
        else:
            incident.latest_alert_event_id = alert_event_id
            incident.correlation_id = correlation_id or incident.correlation_id
            if incident.status in {
                IncidentStatus.failed,
                IncidentStatus.awaiting_human_review,
                IncidentStatus.triaged,
                IncidentStatus.mitigated,
                IncidentStatus.resolved,
                IncidentStatus.postmortem_required,
            }:
                incident.status = IncidentStatus.open
                incident.last_error = None
        self.db.flush()
        return incident

    def attach_incident_version(self, incident: IncidentORM, version: str | None, git_sha: str | None) -> None:
        incident.service_version = version or incident.service_version
        incident.git_sha = git_sha or incident.git_sha
        self.db.flush()

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

    def create_review_decision(self, incident_id: UUID, decision: str, notes: str | None = None) -> ReviewDecisionORM:
        row = ReviewDecisionORM(incident_id=incident_id, decision=decision, notes=notes)
        self.db.add(row)
        self.db.flush()
        return row

    def count_review_decisions(self) -> dict[str, int]:
        rows = self.db.execute(
            select(ReviewDecisionORM.decision, func.count()).group_by(ReviewDecisionORM.decision)
        ).all()
        output = {"approve": 0, "reject": 0}
        for decision, count in rows:
            if decision in output:
                output[decision] = int(count)
        return output

    def create_deployment_event(
        self,
        *,
        service: str,
        env: str,
        deployed_at: datetime,
        version: str | None,
        git_sha: str | None,
        actor: str | None,
        source: str,
        meta: dict,
    ) -> DeploymentEventORM:
        row = DeploymentEventORM(
            service=service,
            env=env,
            deployed_at=deployed_at,
            version=version,
            git_sha=git_sha,
            actor=actor,
            source=source,
            meta=meta,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def list_recent_deployments(self, *, service: str, env: str, since: datetime, until: datetime) -> list[DeploymentEventORM]:
        stmt = (
            select(DeploymentEventORM)
            .where(DeploymentEventORM.service == service)
            .where(DeploymentEventORM.env == env)
            .where(DeploymentEventORM.deployed_at >= since)
            .where(DeploymentEventORM.deployed_at <= until)
            .order_by(desc(DeploymentEventORM.deployed_at))
        )
        return list(self.db.execute(stmt).scalars())

    def create_config_change(
        self,
        *,
        service: str,
        env: str,
        changed_at: datetime,
        actor: str | None,
        diff: dict,
        source: str,
    ) -> ConfigChangeORM:
        row = ConfigChangeORM(
            service=service,
            env=env,
            changed_at=changed_at,
            actor=actor,
            diff=diff,
            source=source,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def list_recent_config_changes(self, *, service: str, env: str, since: datetime, until: datetime) -> list[ConfigChangeORM]:
        stmt = (
            select(ConfigChangeORM)
            .where(ConfigChangeORM.service == service)
            .where(ConfigChangeORM.env == env)
            .where(ConfigChangeORM.changed_at >= since)
            .where(ConfigChangeORM.changed_at <= until)
            .order_by(desc(ConfigChangeORM.changed_at))
        )
        return list(self.db.execute(stmt).scalars())

    def create_feedback(
        self,
        *,
        incident_id: UUID,
        helpful: bool,
        correct: bool | None,
        final_rca: str | None,
        notes: str | None,
    ) -> IncidentFeedbackORM:
        row = IncidentFeedbackORM(
            incident_id=incident_id,
            helpful=helpful,
            correct=correct,
            final_rca=final_rca,
            notes=notes,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def list_feedback(self, incident_id: UUID) -> list[IncidentFeedbackORM]:
        stmt = (
            select(IncidentFeedbackORM)
            .where(IncidentFeedbackORM.incident_id == incident_id)
            .order_by(desc(IncidentFeedbackORM.created_at))
        )
        return list(self.db.execute(stmt).scalars())

    def create_audit_log(
        self,
        *,
        actor: str,
        action: str,
        resource_type: str,
        resource_id: str | None,
        details: dict,
    ) -> AuditLogORM:
        row = AuditLogORM(
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def create_pipeline_run(
        self,
        *,
        incident_id: UUID | None,
        stage: str,
        status: str,
        duration_ms: int,
        error: str | None,
        metrics: dict,
    ) -> PipelineRunORM:
        row = PipelineRunORM(
            incident_id=incident_id,
            stage=stage,
            status=status,
            duration_ms=duration_ms,
            error=error,
            metrics=metrics,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def runtime_metrics(self) -> dict:
        run_rows = self.db.execute(select(PipelineRunORM)).scalars().all()
        failures = sum(1 for row in run_rows if row.status == "failed")
        llm_failures = sum(1 for row in run_rows if row.stage == "llm" and row.status == "failed")
        durations = [row.duration_ms for row in run_rows if row.duration_ms > 0]
        recent_rows = (
            self.db.execute(select(PipelineRunORM).order_by(desc(PipelineRunORM.created_at)).limit(20)).scalars().all()
        )
        return {
            "pipeline_runs": len(run_rows),
            "pipeline_failures": failures,
            "llm_failures": llm_failures,
            "avg_pipeline_duration_ms": int(sum(durations) / len(durations)) if durations else 0,
            "recent_runs": [
                {
                    "id": str(row.id),
                    "incident_id": str(row.incident_id) if row.incident_id else None,
                    "stage": row.stage,
                    "status": row.status,
                    "duration_ms": row.duration_ms,
                    "error": row.error,
                    "metrics": row.metrics,
                    "created_at": row.created_at,
                }
                for row in recent_rows
            ],
        }

    def purge_old_data(self, before: datetime) -> dict[str, int]:
        evidence_deleted = self.db.execute(
            delete(EvidencePackORM).where(EvidencePackORM.created_at < before)
        ).rowcount or 0
        report_deleted = self.db.execute(
            delete(TriageReportORM).where(TriageReportORM.created_at < before)
        ).rowcount or 0
        decision_deleted = self.db.execute(
            delete(ReviewDecisionORM).where(ReviewDecisionORM.created_at < before)
        ).rowcount or 0
        feedback_deleted = self.db.execute(
            delete(IncidentFeedbackORM).where(IncidentFeedbackORM.created_at < before)
        ).rowcount or 0
        deploy_deleted = self.db.execute(
            delete(DeploymentEventORM).where(DeploymentEventORM.created_at < before)
        ).rowcount or 0
        config_deleted = self.db.execute(
            delete(ConfigChangeORM).where(ConfigChangeORM.created_at < before)
        ).rowcount or 0
        incident_deleted = self.db.execute(
            delete(IncidentORM).where(IncidentORM.updated_at < before)
        ).rowcount or 0
        self.db.flush()
        return {
            "evidence_deleted": int(evidence_deleted),
            "report_deleted": int(report_deleted),
            "decision_deleted": int(decision_deleted),
            "feedback_deleted": int(feedback_deleted),
            "deploy_deleted": int(deploy_deleted),
            "config_deleted": int(config_deleted),
            "incident_deleted": int(incident_deleted),
        }
