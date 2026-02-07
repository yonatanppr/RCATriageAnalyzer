import json
from pathlib import Path

from eval.offline_eval import score_report


def test_offline_eval_scores_ground_truth_fixture() -> None:
    fixture = Path(__file__).resolve().parents[2] / "fixtures" / "ground_truth_expected_report.json"
    report = json.loads(fixture.read_text(encoding="utf-8"))
    result = score_report(report)
    assert result["uncited_facts"] == 0
    assert result["hypothesis_alignment"] >= 0.0
