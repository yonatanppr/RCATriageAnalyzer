from app.services.normalization import normalize_alertmanager_payload


def test_alertmanager_normalization_to_alert_event() -> None:
    payload = {
        "groupKey": "g1",
        "status": "firing",
        "commonLabels": {
            "alertname": "high-error-rate",
            "service": "checkout-api",
            "env": "prod",
            "severity": "critical",
            "correlation_id": "req-123",
        },
        "commonAnnotations": {"summary": "high error rate"},
        "alerts": [],
    }
    event = normalize_alertmanager_payload(payload)
    assert event.source == "alertmanager"
    assert event.correlation_id == "req-123"
    assert event.resource_refs["service"] == "checkout-api"
