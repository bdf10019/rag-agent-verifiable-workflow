from __future__ import annotations

from pathlib import Path

import pytest

from opsflow_agent.database import (
    Database,
    IdempotencyConflictError,
    InvalidTransitionError,
)
from opsflow_agent.demo import demo_requests
from opsflow_agent.models import IncidentRequest, RiskLevel, RunStatus
from opsflow_agent.orchestrator import WorkflowOrchestrator
from opsflow_agent.settings import Settings


def request(name: str, key: str) -> IncidentRequest:
    payload = dict(demo_requests()[name])
    payload["idempotency_key"] = key
    return IncidentRequest.model_validate(payload)


def test_critical_run_stops_at_human_gate(
    orchestrator: WorkflowOrchestrator, database: Database
) -> None:
    run = orchestrator.submit(request("critical", "critical-test-001"))

    assert run.status == RunStatus.needs_review
    assert run.risk_level == RiskLevel.critical
    assert run.recommendation is not None
    assert run.recommendation.requires_human_approval is True
    assert any(item.startswith("telemetry:") for item in run.recommendation.citations)
    assert any(item.startswith("sop:") for item in run.recommendation.citations)
    assert {item.tool_name.value for item in run.tool_executions if item.status == "succeeded"} == {
        "lookup_telemetry",
        "lookup_maintenance_history",
        "search_sop",
        "calculate_risk",
    }

    approved = database.decide_approval(run.run_id, "reviewer", "approved", "Evidence checked")
    assert approved.status == RunStatus.completed
    assert approved.approval is not None
    assert approved.approval["decision"] == "approved"


def test_normal_run_completes_without_review(orchestrator: WorkflowOrchestrator) -> None:
    run = orchestrator.submit(request("normal", "normal-test-001"))

    assert run.status == RunStatus.completed
    assert run.risk_level == RiskLevel.low
    assert run.recommendation is not None
    assert run.recommendation.requires_human_approval is False

    with pytest.raises(InvalidTransitionError):
        orchestrator.database.transition(run.run_id, RunStatus.validating, "invalid_restart")


def test_idempotent_request_returns_same_run(orchestrator: WorkflowOrchestrator) -> None:
    incident = request("normal", "idempotent-test-001")
    first = orchestrator.submit(incident)
    second = orchestrator.submit(incident)

    assert first.run_id == second.run_id
    assert len(second.tool_executions) == len(first.tool_executions)

    changed = incident.model_copy(update={"question": "A different investigation question."})
    with pytest.raises(IdempotencyConflictError):
        orchestrator.submit(changed)


def test_transient_tool_failure_is_retried(tmp_path: Path) -> None:
    settings = Settings(
        database_path=tmp_path / "retry.db",
        sop_directory=Settings().sop_directory,
        fail_once_tool="lookup_telemetry",
        max_tool_attempts=3,
    ).normalized()
    database = Database(Path(settings.database_path))
    database.initialize()
    database.seed_demo_data(Path(settings.sop_directory))
    orchestrator = WorkflowOrchestrator(database, settings)

    run = orchestrator.submit(request("normal", "retry-test-001"))

    telemetry_attempts = [
        item for item in run.tool_executions if item.tool_name.value == "lookup_telemetry"
    ]
    assert run.status == RunStatus.completed
    assert [item.status for item in telemetry_attempts] == ["failed", "succeeded"]
    assert any(item["event_type"] == "tool_retry_scheduled" for item in run.events)


def test_failed_run_can_resume_and_reuse_state(tmp_path: Path) -> None:
    settings = Settings(
        database_path=tmp_path / "resume.db",
        sop_directory=Settings().sop_directory,
        fail_once_tool="lookup_telemetry",
        max_tool_attempts=1,
    ).normalized()
    database = Database(Path(settings.database_path))
    database.initialize()
    database.seed_demo_data(Path(settings.sop_directory))
    orchestrator = WorkflowOrchestrator(database, settings)

    failed = orchestrator.submit(request("normal", "resume-test-001"))
    resumed = orchestrator.resume(failed.run_id)

    assert failed.status == RunStatus.failed
    assert resumed.status == RunStatus.completed
    assert any(item["event_type"] == "run_resumed" for item in resumed.events)
    telemetry_attempts = [
        item for item in resumed.tool_executions if item.tool_name.value == "lookup_telemetry"
    ]
    assert [item.status for item in telemetry_attempts] == ["failed", "succeeded"]


def test_missing_operational_evidence_requires_review(orchestrator: WorkflowOrchestrator) -> None:
    incident = IncidentRequest(
        idempotency_key="missing-test-001",
        asset_id="ASSET-404",
        occurred_at="2026-01-15T10:30:00Z",
        symptoms=["unknown status"],
        severity="medium",
        question="Investigate the asset despite incomplete operational evidence.",
    )
    run = orchestrator.submit(incident)

    assert run.status == RunStatus.needs_review
    assert run.recommendation is not None
    assert "No telemetry was available" in " ".join(run.recommendation.limitations)
