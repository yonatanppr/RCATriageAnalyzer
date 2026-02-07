"""Celery wiring."""

from celery import Celery

from app.config import get_settings

settings = get_settings()
celery_app = Celery("iats", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


def enqueue_triage(incident_id: str) -> None:
    """Queue triage task."""

    triage_incident.apply_async(args=(incident_id,), kwargs={})


@celery_app.task(
    name="triage_incident",
    autoretry_for=(Exception,),
    retry_backoff=settings.celery_retry_backoff_seconds,
    retry_jitter=settings.celery_retry_jitter,
    max_retries=settings.celery_task_max_retries,
)
def triage_incident(incident_id: str) -> None:
    """Celery task entrypoint."""

    from app.services.triage import triage_incident_sync

    triage_incident_sync(incident_id)
