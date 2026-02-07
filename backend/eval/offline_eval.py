"""Offline evaluation harness for report structure and citation quality."""

from __future__ import annotations

import json
from pathlib import Path

from app.domain.models import TriageReportPayload


def score_report(report: dict) -> dict:
    model = TriageReportPayload.model_validate(report)
    uncited_facts = sum(1 for fact in model.facts if not fact.evidence_refs)
    hypothesis_alignment = 1.0 if model.hypotheses else 0.0
    evidence_relevance = min(1.0, sum(len(f.evidence_refs) for f in model.facts) / 5.0) if model.facts else 0.0
    usefulness_next_checks = 1.0 if model.next_checks else 0.0
    return {
        "uncited_facts": uncited_facts,
        "hypothesis_alignment": hypothesis_alignment,
        "evidence_relevance": round(evidence_relevance, 3),
        "usefulness_next_checks": usefulness_next_checks,
        "mode": model.mode,
    }


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    fixture_path = root / "fixtures" / "ground_truth_expected_report.json"
    report = json.loads(fixture_path.read_text(encoding="utf-8"))
    result = score_report(report)
    out = root / "backend" / "eval" / "last_eval_report.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
