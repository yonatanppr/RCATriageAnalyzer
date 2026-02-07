"""Alert normalization service."""

from app.adapters.cloudwatch import CloudWatchAlertAdapter
from app.domain.models import AlertEvent


def normalize_cloudwatch_payload(payload: dict) -> AlertEvent:
    """Normalize CloudWatch payload into canonical alert event."""

    return CloudWatchAlertAdapter().normalize(payload)
