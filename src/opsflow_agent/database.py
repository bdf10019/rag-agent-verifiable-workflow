from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import (
    IncidentRequest,
    Recommendation,
    RiskLevel,
    RunStatus,
    RunView,
    ToolExecution,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS telemetry (
    asset_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    air_temp REAL NOT NULL,
    process_temp REAL NOT NULL,
    rpm INTEGER NOT NULL,
    torque REAL NOT NULL,
    tool_wear INTEGER NOT NULL,
    machine_failure INTEGER NOT NULL CHECK (machine_failure IN (0, 1)),
    failure_mode TEXT,
    source TEXT NOT NULL,
    PRIMARY KEY (asset_id, observed_at)
);

CREATE TABLE IF NOT EXISTS maintenance_events (
    event_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    event_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    resolution TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    section TEXT NOT NULL,
    content TEXT NOT NULL,
    source_path TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    current_step TEXT NOT NULL,
    risk_level TEXT,
    recommendation_json TEXT,
    failure_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS tool_calls (
    call_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    step_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    args_json TEXT NOT NULL,
    result_json TEXT,
    status TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    duration_ms REAL NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_tool_calls_run ON tool_calls(run_id, call_id);

CREATE TABLE IF NOT EXISTS workflow_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    event_type TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT,
    detail_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_workflow_events_run ON workflow_events(run_id, event_id);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE REFERENCES runs(run_id),
    reviewer TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
    note TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

ALLOWED_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.submitted: {RunStatus.validating, RunStatus.failed},
    RunStatus.validating: {RunStatus.planning, RunStatus.failed},
    RunStatus.planning: {RunStatus.gathering_evidence, RunStatus.failed},
    RunStatus.gathering_evidence: {RunStatus.verifying, RunStatus.failed},
    RunStatus.verifying: {RunStatus.needs_review, RunStatus.completed, RunStatus.failed},
    RunStatus.needs_review: {RunStatus.completed, RunStatus.cancelled},
    RunStatus.failed: {RunStatus.validating},
    RunStatus.completed: set(),
    RunStatus.cancelled: set(),
}


class IdempotencyConflictError(ValueError):
    pass


class InvalidTransitionError(ValueError):
    pass


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def seed_demo_data(self, sop_directory: Path) -> dict[str, int]:
        telemetry_rows = [
            ("ASSET-001", "2026-01-15T06:00:00+00:00", 298.2, 307.3, 1460, 42.0, 218, 0, None),
            ("ASSET-001", "2026-01-15T07:00:00+00:00", 299.1, 310.5, 1410, 47.8, 224, 0, None),
            (
                "ASSET-001",
                "2026-01-15T08:00:00+00:00",
                300.3,
                316.9,
                1320,
                54.5,
                231,
                1,
                "heat_dissipation",
            ),
            (
                "ASSET-001",
                "2026-01-15T09:00:00+00:00",
                301.0,
                321.4,
                1280,
                57.2,
                239,
                1,
                "overstrain",
            ),
            (
                "ASSET-001",
                "2026-01-15T10:00:00+00:00",
                300.8,
                319.7,
                1305,
                55.9,
                244,
                1,
                "tool_wear",
            ),
            ("ASSET-002", "2026-01-15T06:00:00+00:00", 297.8, 306.1, 1510, 38.0, 40, 0, None),
            ("ASSET-002", "2026-01-15T07:00:00+00:00", 298.0, 306.5, 1500, 39.1, 43, 0, None),
            ("ASSET-002", "2026-01-15T08:00:00+00:00", 298.2, 307.0, 1490, 39.5, 46, 0, None),
            ("ASSET-002", "2026-01-15T09:00:00+00:00", 298.1, 306.8, 1505, 38.8, 49, 0, None),
            ("ASSET-002", "2026-01-15T10:00:00+00:00", 298.3, 307.2, 1498, 39.0, 52, 0, None),
        ]
        maintenance_rows = [
            (
                "MNT-001",
                "ASSET-001",
                "2025-12-18T03:30:00+00:00",
                "inspection",
                "Rising process temperature during sustained load.",
                "Cleaned cooling path and verified airflow.",
            ),
            (
                "MNT-002",
                "ASSET-001",
                "2026-01-03T05:10:00+00:00",
                "tool_change",
                "Tool wear reached the preventive replacement threshold.",
                "Replaced tool and recorded baseline vibration.",
            ),
            (
                "MNT-003",
                "ASSET-002",
                "2025-12-20T02:00:00+00:00",
                "preventive",
                "Scheduled monthly inspection.",
                "No abnormal condition found.",
            ),
        ]
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT OR IGNORE INTO telemetry
                (asset_id, observed_at, air_temp, process_temp, rpm, torque, tool_wear,
                 machine_failure, failure_mode, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'original_demo_fixture')
                """,
                telemetry_rows,
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO maintenance_events
                (event_id, asset_id, occurred_at, event_type, summary, resolution)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                maintenance_rows,
            )
        document_count = self.index_sop_directory(sop_directory)
        return {
            "telemetry": len(telemetry_rows),
            "maintenance_events": len(maintenance_rows),
            "documents": document_count,
        }

    def index_sop_directory(self, directory: Path) -> int:
        if not directory.exists():
            return 0
        indexed = 0
        for path in sorted(directory.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            title = path.stem.replace("-", " ").title()
            sections = self._split_markdown(text)
            for section_name, content in sections:
                content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                stable_name = f"{path.stem}:{self._slug(section_name)}"
                doc_id = f"sop:{stable_name}"
                with self.connect() as connection:
                    connection.execute(
                        """
                        INSERT INTO documents
                        (doc_id, title, section, content, source_path, content_hash)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(doc_id) DO UPDATE SET
                          title=excluded.title,
                          section=excluded.section,
                          content=excluded.content,
                          source_path=excluded.source_path,
                          content_hash=excluded.content_hash
                        """,
                        (
                            doc_id,
                            title,
                            section_name,
                            content,
                            f"resources/sops/{path.name}",
                            content_hash,
                        ),
                    )
                indexed += 1
        return indexed

    @staticmethod
    def _split_markdown(text: str) -> list[tuple[str, str]]:
        sections: list[tuple[str, str]] = []
        heading = "Overview"
        buffer: list[str] = []
        for line in text.splitlines():
            if line.startswith("## "):
                if buffer and " ".join(buffer).strip():
                    sections.append((heading, "\n".join(buffer).strip()))
                heading = line[3:].strip()
                buffer = []
            elif not line.startswith("# "):
                buffer.append(line)
        if buffer and " ".join(buffer).strip():
            sections.append((heading, "\n".join(buffer).strip()))
        return sections

    @staticmethod
    def _slug(value: str) -> str:
        chars = [character.lower() if character.isalnum() else "-" for character in value]
        return "-".join(filter(None, "".join(chars).split("-"))) or "section"

    def create_or_get_run(self, request: IncidentRequest) -> tuple[str, bool]:
        request_data = request.model_dump(mode="json")
        request_json = canonical_json(request_data)
        request_hash = hashlib.sha256(request_json.encode("utf-8")).hexdigest()
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT run_id, request_hash FROM runs WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing:
                if existing["request_hash"] != request_hash:
                    raise IdempotencyConflictError(
                        "idempotency key already exists for a different request"
                    )
                return str(existing["run_id"]), False

            run_id = f"run_{uuid.uuid4().hex[:16]}"
            trace_id = uuid.uuid4().hex
            timestamp = now_iso()
            connection.execute(
                """
                INSERT INTO runs
                (run_id, trace_id, idempotency_key, request_json, request_hash, status,
                 current_step, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    trace_id,
                    request.idempotency_key,
                    request_json,
                    request_hash,
                    RunStatus.submitted.value,
                    "request_received",
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                """
                INSERT INTO workflow_events
                (run_id, event_type, from_status, to_status, detail_json, created_at)
                VALUES (?, 'run_created', NULL, ?, '{}', ?)
                """,
                (run_id, RunStatus.submitted.value, timestamp),
            )
            return run_id, True

    def transition(
        self,
        run_id: str,
        to_status: RunStatus,
        current_step: str,
        detail: dict[str, Any] | None = None,
        *,
        risk_level: RiskLevel | None = None,
        recommendation: Recommendation | None = None,
        failure_reason: str | None = None,
    ) -> None:
        timestamp = now_iso()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT status FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if not row:
                raise KeyError(run_id)
            from_status = str(row["status"])
            from_status_enum = RunStatus(from_status)
            if to_status not in ALLOWED_TRANSITIONS[from_status_enum]:
                raise InvalidTransitionError(
                    f"invalid workflow transition: {from_status_enum.value} -> {to_status.value}"
                )
            completed_at = (
                timestamp
                if to_status in {RunStatus.completed, RunStatus.cancelled, RunStatus.failed}
                else None
            )
            connection.execute(
                """
                UPDATE runs SET status=?, current_step=?, risk_level=COALESCE(?, risk_level),
                    recommendation_json=COALESCE(?, recommendation_json),
                    failure_reason=?, updated_at=?, completed_at=?
                WHERE run_id=?
                """,
                (
                    to_status.value,
                    current_step,
                    risk_level.value if risk_level else None,
                    recommendation.model_dump_json() if recommendation else None,
                    failure_reason,
                    timestamp,
                    completed_at,
                    run_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO workflow_events
                (run_id, event_type, from_status, to_status, detail_json, created_at)
                VALUES (?, 'state_transition', ?, ?, ?, ?)
                """,
                (run_id, from_status, to_status.value, canonical_json(detail or {}), timestamp),
            )

    def add_event(self, run_id: str, event_type: str, detail: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO workflow_events
                (run_id, event_type, from_status, to_status, detail_json, created_at)
                VALUES (?, ?, NULL, NULL, ?, ?)
                """,
                (run_id, event_type, canonical_json(detail), now_iso()),
            )

    def record_tool_call(
        self,
        run_id: str,
        step_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any] | None,
        status: str,
        attempt: int,
        duration_ms: float,
        error: str | None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO tool_calls
                (run_id, step_id, tool_name, args_json, result_json, status, attempt,
                 duration_ms, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    step_id,
                    tool_name,
                    canonical_json(arguments),
                    canonical_json(result) if result is not None else None,
                    status,
                    attempt,
                    duration_ms,
                    error,
                    now_iso(),
                ),
            )

    def successful_tool_results(self, run_id: str) -> dict[str, dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT tool_name, result_json FROM tool_calls
                WHERE run_id=? AND status='succeeded' ORDER BY call_id
                """,
                (run_id,),
            ).fetchall()
        results: dict[str, dict[str, Any]] = {}
        for row in rows:
            results[str(row["tool_name"])] = json.loads(row["result_json"])
        return results

    def get_run(self, run_id: str) -> RunView:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if not row:
                raise KeyError(run_id)
            tool_rows = connection.execute(
                "SELECT * FROM tool_calls WHERE run_id=? ORDER BY call_id", (run_id,)
            ).fetchall()
            event_rows = connection.execute(
                "SELECT * FROM workflow_events WHERE run_id=? ORDER BY event_id", (run_id,)
            ).fetchall()
            approval_row = connection.execute(
                "SELECT reviewer, decision, note, created_at FROM approvals WHERE run_id=?",
                (run_id,),
            ).fetchone()

        tool_executions = [
            ToolExecution(
                tool_name=item["tool_name"],
                status=item["status"],
                attempts=item["attempt"],
                duration_ms=item["duration_ms"],
                result=json.loads(item["result_json"]) if item["result_json"] else None,
                error=item["error"],
            )
            for item in tool_rows
        ]
        events = [
            {
                "event_id": item["event_id"],
                "event_type": item["event_type"],
                "from_status": item["from_status"],
                "to_status": item["to_status"],
                "detail": json.loads(item["detail_json"]),
                "created_at": item["created_at"],
            }
            for item in event_rows
        ]
        approval = dict(approval_row) if approval_row else None
        return RunView(
            run_id=row["run_id"],
            trace_id=row["trace_id"],
            status=row["status"],
            current_step=row["current_step"],
            request=IncidentRequest.model_validate_json(row["request_json"]),
            risk_level=row["risk_level"],
            recommendation=(
                Recommendation.model_validate_json(row["recommendation_json"])
                if row["recommendation_json"]
                else None
            ),
            failure_reason=row["failure_reason"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            tool_executions=tool_executions,
            events=events,
            approval=approval,
        )

    def list_runs(self, limit: int = 50) -> list[RunView]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT run_id FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self.get_run(str(row["run_id"])) for row in rows]

    def decide_approval(self, run_id: str, reviewer: str, decision: str, note: str) -> RunView:
        run = self.get_run(run_id)
        if run.status != RunStatus.needs_review:
            raise InvalidTransitionError("only runs awaiting review can be decided")
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO approvals (run_id, reviewer, decision, note, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, reviewer, decision, note, now_iso()),
            )
        final_status = RunStatus.completed if decision == "approved" else RunStatus.cancelled
        self.transition(
            run_id,
            final_status,
            f"human_{decision}",
            {"reviewer": reviewer, "decision": decision},
        )
        return self.get_run(run_id)

    def metrics(self) -> dict[str, Any]:
        with self.connect() as connection:
            status_rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM runs GROUP BY status"
            ).fetchall()
            tool_rows = connection.execute(
                """
                SELECT status, COUNT(*) AS count, AVG(duration_ms) AS average_ms
                FROM tool_calls GROUP BY status
                """
            ).fetchall()
            total = connection.execute("SELECT COUNT(*) AS count FROM runs").fetchone()["count"]
        return {
            "runs_total": total,
            "runs_by_status": {row["status"]: row["count"] for row in status_rows},
            "tool_calls": {
                row["status"]: {"count": row["count"], "average_ms": row["average_ms"] or 0}
                for row in tool_rows
            },
        }
