import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app



def test_fixture_pipeline_post_alert_runs_and_stores_report_or_failure() -> None:
    payload = json.loads((Path(__file__).resolve().parents[2] / "fixtures" / "cloudwatch_alarm_event.json").read_text())

    with TestClient(app) as client:
        resp = client.post("/v1/alerts/cloudwatch", json=payload)
        assert resp.status_code == 200
        incident_id = resp.json()["incident_id"]

        detail_resp = client.get(f"/v1/incidents/{incident_id}")
        assert detail_resp.status_code == 200
        status = detail_resp.json()["status"]
        assert status in ["failed", "triaged"]

        evidence_resp = client.get(f"/v1/incidents/{incident_id}/evidence")
        assert evidence_resp.status_code == 200
        assert evidence_resp.json() is not None

        report_resp = client.get(f"/v1/incidents/{incident_id}/report")
        assert report_resp.status_code == 200
        data = report_resp.json()
        if status == "failed":
            assert data["message"] == "LLM unavailable or not configured"
        else:
            assert "summary" in data
