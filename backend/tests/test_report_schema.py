import pytest

from app.domain.models import TriageReportPayload


def _ref(artifact_id: str, pointer: str) -> dict:
    return {"artifact_id": artifact_id, "pointer": pointer}


def test_report_schema_valid_example() -> None:
    payload = {
        "summary": "Checkout errors correlate with a recent deploy.",
        "mode": "normal",
        "facts": [
            {
                "claim_id": "fact-1",
                "text": "Error signature TimeoutException spiked after alert.",
                "evidence_refs": [_ref("art-logs", "log_line_range:1-10")],
            }
        ],
        "hypotheses": [
            {
                "rank": 1,
                "title": "Upstream timeout behavior changed in latest deploy.",
                "explanation": "Repeated timeout signatures overlap deployment window.",
                "confidence": 0.74,
                "evidence_refs": [_ref("art-deploy", "query_id:deploy-timeline")],
                "disconfirming_signals": ["No timeout logs in expanded window"],
                "missing_data": ["Dependency latency metrics"],
            }
        ],
        "next_checks": [
            {
                "check_id": "check-1",
                "step": "Re-run query with +15 minute window.",
                "command_or_query": "fields @message",
                "evidence_refs": [_ref("art-query", "query_id:q-errors")],
            }
        ],
        "mitigations": [
            {
                "mitigation_id": "mit-1",
                "action": "Rollback deployment to previous SHA.",
                "risk": "Potential feature regression.",
                "evidence_refs": [_ref("art-deploy", "query_id:deploy-timeline")],
            }
        ],
        "claims": [
            {
                "claim_id": "claim-1",
                "type": "fact",
                "text": "Timeouts increased.",
                "evidence_refs": [_ref("art-logs", "log_line_range:1-10")],
            }
        ],
        "uncertainty_note": None,
    }
    model = TriageReportPayload.model_validate(payload)
    assert model.summary.startswith("Checkout")


def test_report_schema_rejects_fact_without_citation() -> None:
    payload = {
        "summary": "x",
        "mode": "normal",
        "facts": [{"claim_id": "f1", "text": "x", "evidence_refs": []}],
        "hypotheses": [],
        "next_checks": [],
        "mitigations": [],
        "claims": [],
        "uncertainty_note": None,
    }
    with pytest.raises(Exception):
        TriageReportPayload.model_validate(payload)
