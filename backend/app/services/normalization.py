"""Alert normalization service."""

from app.adapters.alertmanager import AlertmanagerAdapter
from app.adapters.cloudwatch import CloudWatchAlertAdapter
from app.domain.models import AlertEvent


def normalize_cloudwatch_payload(payload: dict) -> AlertEvent:
    """Normalize CloudWatch payload into canonical alert event."""

    return CloudWatchAlertAdapter().normalize(payload)


def normalize_alertmanager_payload(payload: dict) -> AlertEvent:
    """Normalize Alertmanager payload into canonical alert event."""

    return AlertmanagerAdapter().normalize(payload)
