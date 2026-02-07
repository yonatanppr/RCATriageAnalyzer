import json
from pathlib import Path

from app.services.normalization import normalize_cloudwatch_payload
from app.utils.hashing import dedup_key_for


def test_cloudwatch_normalization_to_alert_event() -> None:
    payload = json.loads((Path(__file__).resolve().parents[2] / "fixtures" / "cloudwatch_alarm_event.json").read_text())
    event = normalize_cloudwatch_payload(payload)

    assert event.source == "cloudwatch"
    assert event.resource_refs["alarm_name"] == "iats-demo-high-error-rate"
    assert event.state == "ALARM"
    assert event.labels["region"] == "us-east-1"


def test_cloudwatch_normalization_extracts_correlation_id_from_reason() -> None:
    payload = {
        "id": "1",
        "source": "aws.cloudwatch",
        "region": "us-east-1",
        "account": "123",
        "detail": {
            "alarmName": "a1",
            "state": {
                "value": "ALARM",
                "reason": "High error rate correlation_id=req-9f8e7d6c",
                "timestamp": "2026-02-06T11:59:00Z",
            },
            "previousState": {"value": "OK"},
        },
    }
    event = normalize_cloudwatch_payload(payload)
    assert event.correlation_id == "req-9f8e7d6c"


def test_dedup_key_is_stable() -> None:
    labels_a = {"b": "2", "a": "1"}
    labels_b = {"a": "1", "b": "2"}
    key_a = dedup_key_for("svc", "prod", "alarm", labels_a)
    key_b = dedup_key_for("svc", "prod", "alarm", labels_b)

    assert key_a == key_b


def test_dedup_key_changes_when_correlation_changes() -> None:
    labels = {"a": "1"}
    key_a = dedup_key_for("svc", "prod", "alarm", labels, "req-1")
    key_b = dedup_key_for("svc", "prod", "alarm", labels, "req-2")
    assert key_a != key_b
