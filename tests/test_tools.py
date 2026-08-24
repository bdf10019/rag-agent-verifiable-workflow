from __future__ import annotations

from opsflow_agent.database import Database
from opsflow_agent.models import ToolName
from opsflow_agent.tools import ToolRegistry


def test_sop_search_returns_server_owned_citations(database: Database) -> None:
    registry = ToolRegistry(database)
    result = registry.invoke(
        ToolName.search_sop,
        {"query": "overheating high torque safe isolation inspection"},
    )

    assert result["matches"]
    assert all(item["citation"].startswith("sop:") for item in result["evidence"])
    assert all(item["source_path"].startswith("resources/sops/") for item in result["matches"])


def test_telemetry_tool_uses_typed_arguments(database: Database) -> None:
    registry = ToolRegistry(database)
    result = registry.invoke(
        ToolName.lookup_telemetry,
        {
            "asset_id": "ASSET-001",
            "occurred_at": "2026-01-15T10:30:00+00:00",
            "window_hours": 24,
        },
    )

    assert result["row_count"] == 5
    assert result["metrics"]["failure_observations"] == 3
    assert result["metrics"]["max_tool_wear"] == 244


def test_risk_calculator_is_deterministic(database: Database) -> None:
    registry = ToolRegistry(database)
    result = registry.invoke(
        ToolName.calculate_risk,
        {
            "severity": "high",
            "metrics": {
                "failure_observations": 2,
                "max_process_temp": 321,
                "max_tool_wear": 244,
                "max_torque": 55,
            },
        },
    )

    assert result["risk_level"] == "critical"
    assert result["score"] == 14
