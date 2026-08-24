from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class Severity(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class RiskLevel(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class RunStatus(StrEnum):
    submitted = "submitted"
    validating = "validating"
    planning = "planning"
    gathering_evidence = "gathering_evidence"
    verifying = "verifying"
    needs_review = "needs_review"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class ToolName(StrEnum):
    lookup_telemetry = "lookup_telemetry"
    lookup_maintenance_history = "lookup_maintenance_history"
    search_sop = "search_sop"
    calculate_risk = "calculate_risk"


class IncidentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    asset_id: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")
    occurred_at: datetime
    symptoms: list[str] = Field(min_length=1, max_length=8)
    severity: Severity = Severity.medium
    question: str = Field(min_length=8, max_length=500)

    @field_validator("symptoms")
    @classmethod
    def validate_symptoms(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if not cleaned:
            raise ValueError("at least one non-empty symptom is required")
        if any(len(item) > 100 for item in cleaned):
            raise ValueError("symptoms must be at most 100 characters")
        return list(dict.fromkeys(cleaned))


class PlanStep(BaseModel):
    step_id: str
    tool_name: ToolName
    purpose: str
    arguments: dict[str, Any]


class Evidence(BaseModel):
    citation: str
    title: str
    excerpt: str
    source_type: str
    score: float = Field(ge=0)


class ToolExecution(BaseModel):
    tool_name: ToolName
    status: str
    attempts: int
    duration_ms: float
    result: dict[str, Any] | None = None
    error: str | None = None


class Recommendation(BaseModel):
    summary: str
    risk_level: RiskLevel
    actions: list[str]
    citations: list[str]
    requires_human_approval: bool
    limitations: list[str]


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision: str = Field(pattern=r"^(approved|rejected)$")
    note: str = Field(min_length=3, max_length=500)


class RunView(BaseModel):
    run_id: str
    trace_id: str
    status: RunStatus
    current_step: str
    request: IncidentRequest
    risk_level: RiskLevel | None
    recommendation: Recommendation | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    tool_executions: list[ToolExecution] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    approval: dict[str, Any] | None = None
