from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .models import IncidentRequest
from .orchestrator import WorkflowOrchestrator


def evaluate_cases(
    orchestrator: WorkflowOrchestrator,
    cases_path: Path,
    output_path: Path | None = None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    with cases_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            case = json.loads(line)
            request_data = dict(case["request"])
            request_data["idempotency_key"] = f"eval-{case['case_id']}-{uuid.uuid4().hex[:10]}"
            run = orchestrator.submit(IncidentRequest.model_validate(request_data))
            succeeded_tools = {
                item.tool_name.value for item in run.tool_executions if item.status == "succeeded"
            }
            required_tools = set(case["expected"]["required_tools"])
            citations = run.recommendation.citations if run.recommendation else []
            checks = {
                "status": run.status.value == case["expected"]["status"],
                "risk_level": (
                    run.risk_level is not None
                    and run.risk_level.value == case["expected"]["risk_level"]
                ),
                "required_tools": required_tools.issubset(succeeded_tools),
                "citation_present": bool(citations) == case["expected"]["citation_present"],
            }
            results.append(
                {
                    "case_id": case["case_id"],
                    "line_number": line_number,
                    "run_id": run.run_id,
                    "passed": all(checks.values()),
                    "checks": checks,
                    "actual": {
                        "status": run.status.value,
                        "risk_level": run.risk_level.value if run.risk_level else None,
                        "tools": sorted(succeeded_tools),
                        "citations": citations,
                    },
                }
            )
    passed = sum(1 for item in results if item["passed"])
    report = {
        "suite": "offline_deterministic_v1",
        "case_count": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": passed / len(results) if results else 0,
        "results": results,
    }
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return report
