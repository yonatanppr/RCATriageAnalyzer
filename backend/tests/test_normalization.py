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


def test_dedup_key_is_stable() -> None:
    labels_a = {"b": "2", "a": "1"}
    labels_b = {"a": "1", "b": "2"}
    key_a = dedup_key_for("svc", "prod", "alarm", labels_a)
    key_b = dedup_key_for("svc", "prod", "alarm", labels_b)

    assert key_a == key_b
