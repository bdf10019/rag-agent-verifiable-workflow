from __future__ import annotations

from typing import Any


def demo_requests() -> dict[str, dict[str, Any]]:
    return {
        "critical": {
            "idempotency_key": "demo-critical-001",
            "asset_id": "ASSET-001",
            "occurred_at": "2026-01-15T10:30:00Z",
            "symptoms": ["overheating", "high torque", "tool wear warning"],
            "severity": "high",
            "question": "Investigate the abnormal condition and propose safe next actions.",
        },
        "normal": {
            "idempotency_key": "demo-normal-001",
            "asset_id": "ASSET-002",
            "occurred_at": "2026-01-15T10:30:00Z",
            "symptoms": ["scheduled health review"],
            "severity": "low",
            "question": "Check current evidence and recommend the next monitoring step.",
        },
    }
