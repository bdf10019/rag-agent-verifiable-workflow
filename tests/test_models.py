from __future__ import annotations

import pytest
from pydantic import ValidationError

from opsflow_agent.models import IncidentRequest


def test_incident_contract_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        IncidentRequest.model_validate(
            {
                "idempotency_key": "contract-test-001",
                "asset_id": "ASSET-001",
                "occurred_at": "2026-01-15T10:30:00Z",
                "symptoms": ["overheating"],
                "severity": "high",
                "question": "Investigate the abnormal condition.",
                "raw_sql": "SELECT * FROM telemetry",
            }
        )


def test_incident_contract_rejects_path_like_asset_id() -> None:
    with pytest.raises(ValidationError):
        IncidentRequest(
            idempotency_key="contract-test-002",
            asset_id="../private",
            occurred_at="2026-01-15T10:30:00Z",
            symptoms=["unknown"],
            severity="low",
            question="Investigate the abnormal condition.",
        )
