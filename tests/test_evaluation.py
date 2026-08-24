from __future__ import annotations

from pathlib import Path

from opsflow_agent.evaluation import evaluate_cases
from opsflow_agent.orchestrator import WorkflowOrchestrator
from opsflow_agent.settings import PROJECT_ROOT


def test_offline_evaluation_suite_passes(
    orchestrator: WorkflowOrchestrator, tmp_path: Path
) -> None:
    output = tmp_path / "report.json"
    report = evaluate_cases(
        orchestrator,
        PROJECT_ROOT / "examples" / "evals" / "cases.jsonl",
        output,
    )

    assert report["case_count"] == 3
    assert report["pass_rate"] == 1.0
    assert output.exists()
