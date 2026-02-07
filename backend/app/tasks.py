"""Celery wiring."""

from celery import Celery

from app.config import get_settings

settings = get_settings()
celery_app = Celery("iats", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(task_always_eager=settings.celery_task_always_eager)


def enqueue_triage(incident_id: str) -> None:
    """Queue triage task."""

    triage_incident.delay(incident_id)


@celery_app.task(name="triage_incident")
def triage_incident(incident_id: str) -> None:
    """Celery task entrypoint."""

    from app.services.triage import triage_incident_sync

    triage_incident_sync(incident_id)
