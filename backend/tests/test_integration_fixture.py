import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

AUTH_HEADERS = {"Authorization": "Bearer test-token"}



def test_fixture_pipeline_post_alert_runs_and_stores_report_or_failure() -> None:
    payload = json.loads((Path(__file__).resolve().parents[2] / "fixtures" / "cloudwatch_alarm_event.json").read_text())

    with TestClient(app) as client:
        resp = client.post("/v1/alerts/cloudwatch", json=payload, headers=AUTH_HEADERS)
        assert resp.status_code == 200
        incident_id = resp.json()["incident_id"]

        detail_resp = client.get(f"/v1/incidents/{incident_id}", headers=AUTH_HEADERS)
        assert detail_resp.status_code == 200
        status = detail_resp.json()["status"]
        assert status in ["failed", "awaiting_human_review"]

        evidence_resp = client.get(f"/v1/incidents/{incident_id}/evidence", headers=AUTH_HEADERS)
        assert evidence_resp.status_code == 200
        assert evidence_resp.json() is not None

        report_resp = client.get(f"/v1/incidents/{incident_id}/report", headers=AUTH_HEADERS)
        assert report_resp.status_code == 200
        data = report_resp.json()
        if status == "failed":
            assert data["message"] == "LLM unavailable or not configured"
        else:
            assert "summary" in data
            assert data["decision_required"] == (status == "awaiting_human_review")


def test_decision_endpoint_approves_or_rejects_human_review() -> None:
    payload = json.loads((Path(__file__).resolve().parents[2] / "fixtures" / "cloudwatch_alarm_event.json").read_text())

    with TestClient(app) as client:
        resp = client.post("/v1/alerts/cloudwatch", json=payload, headers=AUTH_HEADERS)
        assert resp.status_code == 200
        incident_id = resp.json()["incident_id"]

        detail_resp = client.get(f"/v1/incidents/{incident_id}", headers=AUTH_HEADERS)
        assert detail_resp.status_code == 200
        status = detail_resp.json()["status"]
        if status != "awaiting_human_review":
            # LLM not configured/available in this test env.
            return

        reject_resp = client.post(
            f"/v1/incidents/{incident_id}/decision",
            json={"decision": "reject", "notes": "needs more evidence"},
            headers=AUTH_HEADERS,
        )
        assert reject_resp.status_code == 200
        assert reject_resp.json()["status"] == "open"

        approve_resp = client.post(
            f"/v1/incidents/{incident_id}/decision",
            json={"decision": "approve"},
            headers=AUTH_HEADERS,
        )
        assert approve_resp.status_code == 409


def test_status_transition_and_metrics_endpoint() -> None:
    payload = json.loads((Path(__file__).resolve().parents[2] / "fixtures" / "cloudwatch_alarm_event.json").read_text())
    with TestClient(app) as client:
        resp = client.post("/v1/alerts/cloudwatch", json=payload, headers=AUTH_HEADERS)
        assert resp.status_code == 200
        incident_id = resp.json()["incident_id"]

        detail = client.get(f"/v1/incidents/{incident_id}", headers=AUTH_HEADERS).json()
        if detail["status"] == "awaiting_human_review":
            approve = client.post(f"/v1/incidents/{incident_id}/decision", json={"decision": "approve"}, headers=AUTH_HEADERS)
            assert approve.status_code == 200

            mitigate = client.post(f"/v1/incidents/{incident_id}/status", json={"status": "mitigated"}, headers=AUTH_HEADERS)
            assert mitigate.status_code == 200
            assert mitigate.json()["status"] == "mitigated"

            resolved = client.post(f"/v1/incidents/{incident_id}/status", json={"status": "resolved"}, headers=AUTH_HEADERS)
            assert resolved.status_code == 200
            assert resolved.json()["status"] == "resolved"

        metrics = client.get("/v1/metrics/quality", headers=AUTH_HEADERS)
        assert metrics.status_code == 200
        data = metrics.json()
        assert "total_incidents" in data
        assert "review_acceptance_rate" in data

        runtime = client.get("/v1/metrics/runtime", headers=AUTH_HEADERS)
        assert runtime.status_code == 200
        assert "pipeline_runs" in runtime.json()


def test_rejects_invalid_alert_payload() -> None:
    with TestClient(app) as client:
        resp = client.post("/v1/alerts/cloudwatch", json={"id": "broken"}, headers=AUTH_HEADERS)
        assert resp.status_code == 422


def test_requires_auth_for_v1_routes() -> None:
    with TestClient(app) as client:
        resp = client.get("/v1/incidents")
        assert resp.status_code == 401
