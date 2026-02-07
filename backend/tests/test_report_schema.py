import pytest

from app.domain.models import TriageReportPayload


def test_report_schema_valid_example() -> None:
    payload = {
        "summary": "Checkout failing due to payment timeout",
        "symptoms": [
            {
                "text": "Timeout exceptions observed",
                "citations": [{"kind": "logs_pattern", "ref_id": "abc123"}],
            }
        ],
        "hypotheses": [
            {
                "rank": 1,
                "title": "Payment provider latency",
                "explanation": "The upstream call timed out repeatedly",
                "confidence": 0.81,
                "citations": [{"kind": "logs_query", "ref_id": "q1"}],
            }
        ],
        "verification_steps": [
            {
                "step": "Run logs query for provider errors",
                "command_or_query": "fields @message",
                "citations": [{"kind": "logs_query", "ref_id": "q1"}],
            }
        ],
        "mitigations": [
            {
                "action": "Enable fallback gateway",
                "risk": "Potential partial degradation",
                "citations": [{"kind": "repo_snippet", "ref_id": "s1"}],
            }
        ],
        "notes": None,
    }
    model = TriageReportPayload.model_validate(payload)
    assert model.summary.startswith("Checkout")


def test_report_schema_rejects_missing_hypothesis_citations() -> None:
    payload = {
        "summary": "x",
        "symptoms": [],
        "hypotheses": [{"rank": 1, "title": "x", "explanation": "x", "confidence": 0.5, "citations": []}],
        "verification_steps": [],
        "mitigations": [],
        "notes": None,
    }
    with pytest.raises(Exception):
        TriageReportPayload.model_validate(payload)
