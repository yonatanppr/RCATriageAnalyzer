import base64
import copy
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

ADMIN_HEADERS = {"Authorization": "Bearer test-token"}


def _fixture_alert() -> dict:
    return json.loads((Path(__file__).resolve().parents[2] / "fixtures" / "cloudwatch_alarm_event.json").read_text())


def _claims_token(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _headers_for_claims(payload: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {_claims_token(payload)}"}


def test_showcase_idempotent_dedup_and_skip_metrics() -> None:
    payload = _fixture_alert()
    with TestClient(app) as client:
        first = client.post("/v1/alerts/cloudwatch", json=payload, headers=ADMIN_HEADERS)
        assert first.status_code == 200
        incident_id = first.json()["incident_id"]

        second = client.post("/v1/alerts/cloudwatch", json=payload, headers=ADMIN_HEADERS)
        assert second.status_code == 200
        assert second.json()["incident_id"] == incident_id

        runtime = client.get("/v1/metrics/runtime", headers=ADMIN_HEADERS)
        assert runtime.status_code == 200
        recent_runs = runtime.json()["recent_runs"]
        triage_runs_for_incident = [r for r in recent_runs if r["stage"] == "triage" and r["incident_id"] == incident_id]
        assert len(triage_runs_for_incident) >= 2


def test_showcase_forced_no_guess_mode_with_targeted_checks(monkeypatch) -> None:
    monkeypatch.setenv("NO_GUESS_CONFIDENCE_THRESHOLD", "0.99")
    payload = _fixture_alert()
    payload["id"] = "showcase-no-guess-1"
    with TestClient(app) as client:
        ingested = client.post("/v1/alerts/cloudwatch", json=payload, headers=ADMIN_HEADERS)
        assert ingested.status_code == 200
        incident_id = ingested.json()["incident_id"]

        report = client.get(f"/v1/incidents/{incident_id}/report", headers=ADMIN_HEADERS)
        assert report.status_code == 200
        body = report.json()
        assert body["mode"] == "insufficient_evidence"
        assert len(body["next_checks"]) >= 1
        assert body["generation_metadata"]["llm_provider"] == "fallback"


def test_showcase_alertmanager_ingestion_path() -> None:
    payload = {
        "groupKey": "showcase-alertmanager-g1",
        "status": "firing",
        "commonLabels": {
            "alertname": "high-error-rate",
            "service": "checkout-api",
            "env": "prod",
            "severity": "critical",
            "correlation_id": "req-alertmanager-123",
        },
        "commonAnnotations": {"summary": "high error rate in checkout"},
        "alerts": [],
    }
    with TestClient(app) as client:
        resp = client.post("/v1/alerts/alertmanager", json=payload, headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        incident_id = resp.json()["incident_id"]
        detail = client.get(f"/v1/incidents/{incident_id}", headers=ADMIN_HEADERS)
        assert detail.status_code == 200
        assert detail.json()["correlation_id"] == "req-alertmanager-123"


def test_showcase_rbac_scoped_access_enforced() -> None:
    payload = _fixture_alert()
    payload["id"] = "showcase-rbac-1"
    with TestClient(app) as client:
        created = client.post("/v1/alerts/cloudwatch", json=payload, headers=ADMIN_HEADERS)
        assert created.status_code == 200
        incident_id = created.json()["incident_id"]

        viewer_headers = _headers_for_claims(
            {"sub": "viewer-a", "role": "viewer", "services": ["payments-api"], "can_ingest": False}
        )
        forbidden = client.get(f"/v1/incidents/{incident_id}", headers=viewer_headers)
        assert forbidden.status_code == 403


def test_showcase_lifecycle_transition_conflict() -> None:
    payload = _fixture_alert()
    payload["id"] = "showcase-status-1"
    with TestClient(app) as client:
        created = client.post("/v1/alerts/cloudwatch", json=payload, headers=ADMIN_HEADERS)
        assert created.status_code == 200
        incident_id = created.json()["incident_id"]

        conflict = client.post(
            f"/v1/incidents/{incident_id}/status",
            json={"status": "resolved"},
            headers=ADMIN_HEADERS,
        )
        assert conflict.status_code == 409


def test_showcase_timeline_includes_deploy_and_config_changes() -> None:
    payload = _fixture_alert()
    payload["id"] = "showcase-timeline-1"
    with TestClient(app) as client:
        dep = client.post(
            "/v1/changes/deployments",
            json={
                "service": "checkout-api",
                "env": "prod",
                "deployed_at": "2026-02-06T11:50:00Z",
                "version": "1.2.99",
                "git_sha": "deadbeef",
            },
            headers=ADMIN_HEADERS,
        )
        assert dep.status_code == 200
        cfg = client.post(
            "/v1/changes/config",
            json={
                "service": "checkout-api",
                "env": "prod",
                "changed_at": "2026-02-06T11:45:00Z",
                "diff": {"feature_flag": {"old": False, "new": True}},
            },
            headers=ADMIN_HEADERS,
        )
        assert cfg.status_code == 200

        created = client.post("/v1/alerts/cloudwatch", json=payload, headers=ADMIN_HEADERS)
        assert created.status_code == 200
        incident_id = created.json()["incident_id"]

        evidence = client.get(f"/v1/incidents/{incident_id}/evidence", headers=ADMIN_HEADERS)
        assert evidence.status_code == 200
        artifacts = evidence.json()["artifacts"]
        timeline = next((a for a in artifacts if a["type"] == "timeline"), None)
        assert timeline is not None
        types = [e["type"] for e in timeline["events"]]
        assert "alert" in types
        assert "deploy" in types
        assert "config" in types


def test_showcase_runtime_metrics_include_llm_endpoint_fields() -> None:
    payload = copy.deepcopy(_fixture_alert())
    payload["id"] = "showcase-runtime-meta-1"
    with TestClient(app) as client:
        created = client.post("/v1/alerts/cloudwatch", json=payload, headers=ADMIN_HEADERS)
        assert created.status_code == 200

        runtime = client.get("/v1/metrics/runtime", headers=ADMIN_HEADERS)
        assert runtime.status_code == 200
        recent_runs = runtime.json()["recent_runs"]
        triage_runs = [r for r in recent_runs if r["stage"] == "triage" and r["status"] == "success"]
        assert triage_runs
        latest = triage_runs[0]["metrics"]
        assert "llm_provider" in latest
        assert "endpoint_failover_count" in latest
        assert "llm_endpoint_used" in latest
