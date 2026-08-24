from __future__ import annotations

from typing import Any

from .database import Database, InvalidTransitionError
from .models import (
    IncidentRequest,
    PlanStep,
    Recommendation,
    RiskLevel,
    RunStatus,
    RunView,
    Severity,
    ToolName,
)
from .settings import Settings
from .tools import FailureInjector, ToolExecutor, ToolFailure, ToolRegistry


class BoundedPlanner:
    """Builds a finite, allowlisted plan from a typed incident request."""

    def __init__(self, max_steps: int) -> None:
        self.max_steps = max_steps

    def build(self, request: IncidentRequest) -> list[PlanStep]:
        occurred_at = request.occurred_at.isoformat()
        search_terms = " ".join(
            [request.question, *request.symptoms, "safety inspection isolation"]
        )
        plan = [
            PlanStep(
                step_id="telemetry",
                tool_name=ToolName.lookup_telemetry,
                purpose="Collect recent measurements without accepting arbitrary SQL.",
                arguments={
                    "asset_id": request.asset_id,
                    "occurred_at": occurred_at,
                    "window_hours": 24,
                },
            ),
            PlanStep(
                step_id="history",
                tool_name=ToolName.lookup_maintenance_history,
                purpose="Find relevant maintenance history for the same asset.",
                arguments={"asset_id": request.asset_id, "occurred_at": occurred_at},
            ),
            PlanStep(
                step_id="sop",
                tool_name=ToolName.search_sop,
                purpose="Retrieve approved generic procedures that can support the recommendation.",
                arguments={"query": search_terms},
            ),
            PlanStep(
                step_id="risk",
                tool_name=ToolName.calculate_risk,
                purpose="Apply deterministic risk rules after evidence collection.",
                arguments={"severity": request.severity.value},
            ),
        ]
        if len(plan) > self.max_steps:
            raise ValueError("generated plan exceeds configured step limit")
        return plan


class WorkflowOrchestrator:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings.normalized()
        registry = ToolRegistry(database, top_k=self.settings.retrieval_top_k)
        injector = FailureInjector(self.settings.fail_once_tool)
        self.executor = ToolExecutor(
            database,
            registry,
            injector,
            max_attempts=self.settings.max_tool_attempts,
            timeout_seconds=self.settings.tool_timeout_seconds,
        )
        self.planner = BoundedPlanner(self.settings.max_plan_steps)

    def submit(self, request: IncidentRequest) -> RunView:
        run_id, created = self.database.create_or_get_run(request)
        if not created:
            return self.database.get_run(run_id)
        return self._execute(run_id)

    def resume(self, run_id: str) -> RunView:
        run = self.database.get_run(run_id)
        if run.status != RunStatus.failed:
            raise InvalidTransitionError("only failed runs can be resumed")
        self.database.add_event(run_id, "run_resumed", {"previous_step": run.current_step})
        return self._execute(run_id)

    def _execute(self, run_id: str) -> RunView:
        run = self.database.get_run(run_id)
        request = run.request
        try:
            self.database.transition(run_id, RunStatus.validating, "validate_request")
            self.database.transition(run_id, RunStatus.planning, "build_bounded_plan")
            plan = self.planner.build(request)
            self.database.add_event(
                run_id,
                "plan_created",
                {
                    "planner": "deterministic_bounded_v1",
                    "steps": [step.model_dump(mode="json") for step in plan],
                },
            )
            self.database.transition(
                run_id,
                RunStatus.gathering_evidence,
                "execute_allowlisted_tools",
            )

            results = self.database.successful_tool_results(run_id)
            for step in plan:
                if step.tool_name.value in results:
                    self.database.add_event(
                        run_id,
                        "tool_result_reused",
                        {"tool_name": step.tool_name.value, "step_id": step.step_id},
                    )
                    continue
                arguments = dict(step.arguments)
                if step.tool_name == ToolName.calculate_risk:
                    telemetry = results.get(ToolName.lookup_telemetry.value, {})
                    arguments["metrics"] = telemetry.get("metrics", {})
                results[step.tool_name.value] = self.executor.execute(
                    run_id,
                    step.step_id,
                    step.tool_name,
                    arguments,
                )

            self.database.transition(run_id, RunStatus.verifying, "verify_evidence_and_policy")
            recommendation = self._build_recommendation(request, results)
            risk_level = recommendation.risk_level
            verification = self._verify(results, recommendation)
            needs_review = recommendation.requires_human_approval or not verification["passed"]
            if needs_review:
                self.database.transition(
                    run_id,
                    RunStatus.needs_review,
                    "human_review_gate",
                    verification,
                    risk_level=risk_level,
                    recommendation=recommendation,
                )
            else:
                self.database.transition(
                    run_id,
                    RunStatus.completed,
                    "result_delivered",
                    verification,
                    risk_level=risk_level,
                    recommendation=recommendation,
                )
        except (ToolFailure, ValueError) as error:
            self.database.transition(
                run_id,
                RunStatus.failed,
                "workflow_failed_closed",
                {"error_type": type(error).__name__},
                failure_reason=str(error),
            )
        return self.database.get_run(run_id)

    def _build_recommendation(
        self,
        request: IncidentRequest,
        results: dict[str, dict[str, Any]],
    ) -> Recommendation:
        risk_result = results.get(ToolName.calculate_risk.value, {})
        risk_level = RiskLevel(risk_result.get("risk_level", RiskLevel.medium.value))
        reasons = list(risk_result.get("reasons", []))
        telemetry = results.get(ToolName.lookup_telemetry.value, {})

        evidence: list[dict[str, Any]] = []
        for tool_name in (
            ToolName.lookup_telemetry,
            ToolName.lookup_maintenance_history,
            ToolName.search_sop,
        ):
            evidence.extend(results.get(tool_name.value, {}).get("evidence", []))
        citations = list(dict.fromkeys(item["citation"] for item in evidence))[:8]

        limitations: list[str] = [
            "The recommendation is decision support and does not replace an approved "
            "site procedure."
        ]
        if telemetry.get("row_count", 0) == 0:
            limitations.append("No telemetry was available in the requested time window.")
        if not results.get(ToolName.search_sop.value, {}).get("matches"):
            limitations.append("No relevant procedure section met the lexical retrieval threshold.")

        if risk_level in {RiskLevel.high, RiskLevel.critical}:
            actions = [
                "Place the asset in a safe state using the locally approved isolation procedure.",
                "Have a qualified operator inspect cooling, load, and tool-wear conditions.",
                "Do not resume operation until measurements and safeguards are independently "
                "verified.",
            ]
        elif risk_level == RiskLevel.medium:
            actions = [
                "Schedule a qualified inspection before the next sustained production window.",
                "Compare current measurements with the asset baseline and document any drift.",
                "Escalate if temperature, torque, or tool-wear values continue to rise.",
            ]
        else:
            actions = [
                "Continue monitored operation within approved limits.",
                "Review the asset again at the next scheduled preventive-maintenance checkpoint.",
            ]

        reason_text = "; ".join(reasons) if reasons else "no elevated deterministic risk signal"
        summary = (
            f"{request.asset_id} was classified as {risk_level.value} risk because {reason_text}. "
            "The workflow used only allowlisted read-only evidence tools."
        )
        requires_human = (
            risk_level in {RiskLevel.high, RiskLevel.critical}
            or telemetry.get("row_count", 0) == 0
            or request.severity in {Severity.high, Severity.critical}
        )
        return Recommendation(
            summary=summary,
            risk_level=risk_level,
            actions=actions,
            citations=citations,
            requires_human_approval=requires_human,
            limitations=limitations,
        )

    @staticmethod
    def _verify(
        results: dict[str, dict[str, Any]], recommendation: Recommendation
    ) -> dict[str, Any]:
        required_tools = {item.value for item in ToolName}
        executed_tools = set(results)
        missing_tools = sorted(required_tools - executed_tools)
        available_citations: set[str] = set()
        for result in results.values():
            available_citations.update(
                item["citation"] for item in result.get("evidence", []) if "citation" in item
            )
        invalid_citations = sorted(set(recommendation.citations) - available_citations)
        has_sop_evidence = any(citation.startswith("sop:") for citation in available_citations)
        has_operational_evidence = any(
            citation.startswith(("telemetry:", "maintenance:")) for citation in available_citations
        )
        checks = {
            "all_required_tools_completed": not missing_tools,
            "citations_are_allowlisted": not invalid_citations,
            "has_sop_evidence": has_sop_evidence,
            "has_operational_evidence": has_operational_evidence,
        }
        return {
            "passed": all(checks.values()),
            "checks": checks,
            "missing_tools": missing_tools,
            "invalid_citations": invalid_citations,
        }
