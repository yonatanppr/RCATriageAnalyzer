"""Alertmanager adapter (stub MVP)."""

from datetime import datetime, timezone
from typing import Any

from app.adapters.interfaces import AlertSourceAdapter
from app.domain.models import AlertEvent


class AlertmanagerAdapter(AlertSourceAdapter):
    def normalize(self, payload: dict[str, Any]) -> AlertEvent:
        labels = payload.get("commonLabels", {}) if isinstance(payload.get("commonLabels"), dict) else {}
        annotations = payload.get("commonAnnotations", {}) if isinstance(payload.get("commonAnnotations"), dict) else {}
        name = labels.get("alertname", "unknown-alertmanager-alert")
        service = labels.get("service", "unknown-service")
        env = labels.get("env", "unknown")
        status = payload.get("status", "firing").upper()
        severity = labels.get("severity", "warning")
        fired_at = datetime.now(timezone.utc)
        return AlertEvent(
            source="alertmanager",
            external_id=str(payload.get("groupKey", name)),
            title=f"Alertmanager: {name}",
            severity=severity,
            state=status,
            correlation_id=labels.get("correlation_id") or labels.get("trace_id"),
            fired_at=fired_at,
            ended_at=None,
            labels={k: str(v) for k, v in labels.items()},
            annotations={k: str(v) for k, v in annotations.items()},
            resource_refs={
                "alert_name": name,
                "service": service,
                "env": env,
            },
            raw_payload=payload,
        )

