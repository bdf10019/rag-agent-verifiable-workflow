from __future__ import annotations

import math
import re
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime, timedelta
from typing import Any

from .database import Database
from .models import RiskLevel, Severity, ToolName


class ToolFailure(RuntimeError):
    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


ToolFunction = Callable[[dict[str, Any]], dict[str, Any]]


def tokenize(value: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[\w-]{2,}", value, flags=re.UNICODE)]


class FailureInjector:
    """Deterministic, opt-in transient failure for recovery demonstrations."""

    def __init__(self, fail_once_tool: str | None = None) -> None:
        self.fail_once_tool = fail_once_tool
        self.triggered: set[str] = set()

    def before_call(self, tool_name: str) -> None:
        if self.fail_once_tool == tool_name and tool_name not in self.triggered:
            self.triggered.add(tool_name)
            raise ToolFailure("injected transient failure", transient=True)


class ToolRegistry:
    def __init__(self, database: Database, *, top_k: int = 3) -> None:
        self.database = database
        self.top_k = top_k
        self._tools: dict[ToolName, ToolFunction] = {
            ToolName.lookup_telemetry: self.lookup_telemetry,
            ToolName.lookup_maintenance_history: self.lookup_maintenance_history,
            ToolName.search_sop: self.search_sop,
            ToolName.calculate_risk: self.calculate_risk,
        }

    @property
    def allowed_tools(self) -> set[ToolName]:
        return set(self._tools)

    def invoke(self, tool_name: ToolName, arguments: dict[str, Any]) -> dict[str, Any]:
        tool = self._tools.get(tool_name)
        if tool is None:
            raise ToolFailure(f"tool is not allowlisted: {tool_name}")
        return tool(arguments)

    def lookup_telemetry(self, arguments: dict[str, Any]) -> dict[str, Any]:
        asset_id = str(arguments["asset_id"])
        occurred_at = datetime.fromisoformat(str(arguments["occurred_at"]))
        start = occurred_at - timedelta(hours=int(arguments.get("window_hours", 24)))
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM telemetry
                WHERE asset_id=? AND observed_at BETWEEN ? AND ?
                ORDER BY observed_at DESC LIMIT 100
                """,
                (asset_id, start.isoformat(), occurred_at.isoformat()),
            ).fetchall()
        if not rows:
            return {
                "asset_id": asset_id,
                "row_count": 0,
                "metrics": {},
                "evidence": [],
                "warning": "no telemetry was found in the requested time window",
            }
        metrics = {
            "max_process_temp": max(float(row["process_temp"]) for row in rows),
            "max_air_temp": max(float(row["air_temp"]) for row in rows),
            "average_rpm": round(sum(int(row["rpm"]) for row in rows) / len(rows), 2),
            "max_torque": max(float(row["torque"]) for row in rows),
            "max_tool_wear": max(int(row["tool_wear"]) for row in rows),
            "failure_observations": sum(int(row["machine_failure"]) for row in rows),
            "failure_modes": sorted({row["failure_mode"] for row in rows if row["failure_mode"]}),
        }
        evidence = [
            {
                "citation": f"telemetry:{asset_id}:{row['observed_at']}",
                "title": f"Telemetry observation for {asset_id}",
                "excerpt": (
                    f"process_temp={row['process_temp']} K, rpm={row['rpm']}, "
                    f"torque={row['torque']} Nm, tool_wear={row['tool_wear']} min, "
                    f"machine_failure={row['machine_failure']}"
                ),
                "source_type": "telemetry",
                "score": 1.0,
            }
            for row in rows[:3]
        ]
        return {
            "asset_id": asset_id,
            "row_count": len(rows),
            "metrics": metrics,
            "evidence": evidence,
        }

    def lookup_maintenance_history(self, arguments: dict[str, Any]) -> dict[str, Any]:
        asset_id = str(arguments["asset_id"])
        occurred_at = str(arguments["occurred_at"])
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM maintenance_events
                WHERE asset_id=? AND occurred_at<=?
                ORDER BY occurred_at DESC LIMIT 10
                """,
                (asset_id, occurred_at),
            ).fetchall()
        events = [dict(row) for row in rows]
        evidence = [
            {
                "citation": f"maintenance:{row['event_id']}",
                "title": f"Maintenance event {row['event_id']}",
                "excerpt": f"{row['summary']} Resolution: {row['resolution']}",
                "source_type": "maintenance_history",
                "score": 0.9,
            }
            for row in rows[:3]
        ]
        return {"asset_id": asset_id, "events": events, "evidence": evidence}

    def search_sop(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments["query"])
        query_terms = Counter(tokenize(query))
        with self.database.connect() as connection:
            rows = connection.execute("SELECT * FROM documents ORDER BY doc_id").fetchall()
        if not rows or not query_terms:
            return {"query": query, "matches": [], "evidence": []}

        document_terms = [Counter(tokenize(str(row["content"]))) for row in rows]
        document_frequency = {
            term: sum(1 for terms in document_terms if term in terms) for term in query_terms
        }
        scored: list[tuple[float, Any]] = []
        for row, terms in zip(rows, document_terms, strict=True):
            score = 0.0
            length = max(sum(terms.values()), 1)
            for term, query_count in query_terms.items():
                if terms[term] == 0:
                    continue
                inverse_frequency = math.log((len(rows) + 1) / (document_frequency[term] + 0.5)) + 1
                score += query_count * (terms[term] / length) * inverse_frequency * 100
            if score > 0:
                scored.append((round(score, 6), row))
        scored.sort(key=lambda item: (-item[0], str(item[1]["doc_id"])))

        matches = []
        evidence = []
        for score, row in scored[: self.top_k]:
            compact = " ".join(str(row["content"]).split())
            excerpt = compact[:280] + ("..." if len(compact) > 280 else "")
            item = {
                "citation": row["doc_id"],
                "title": f"{row['title']} — {row['section']}",
                "excerpt": excerpt,
                "source_type": "sop",
                "score": score,
            }
            matches.append(
                {
                    "doc_id": row["doc_id"],
                    "title": row["title"],
                    "section": row["section"],
                    "source_path": row["source_path"],
                    "score": score,
                }
            )
            evidence.append(item)
        return {"query": query, "matches": matches, "evidence": evidence}

    def calculate_risk(self, arguments: dict[str, Any]) -> dict[str, Any]:
        metrics = dict(arguments.get("metrics") or {})
        severity = Severity(str(arguments.get("severity", Severity.medium.value)))
        score = 0
        reasons: list[str] = []

        failures = int(metrics.get("failure_observations", 0))
        process_temp = float(metrics.get("max_process_temp", 0))
        tool_wear = int(metrics.get("max_tool_wear", 0))
        torque = float(metrics.get("max_torque", 0))

        if failures:
            score += 4
            reasons.append(f"{failures} telemetry observations report machine failure")
        if process_temp >= 320:
            score += 3
            reasons.append(f"process temperature reached {process_temp:.1f} K")
        elif process_temp >= 315:
            score += 2
            reasons.append(f"process temperature is elevated at {process_temp:.1f} K")
        if tool_wear >= 240:
            score += 3
            reasons.append(f"tool wear reached {tool_wear} minutes")
        elif tool_wear >= 200:
            score += 2
            reasons.append(f"tool wear is elevated at {tool_wear} minutes")
        if torque >= 50:
            score += 2
            reasons.append(f"torque reached {torque:.1f} Nm")
        if severity == Severity.critical:
            score += 4
            reasons.append("the submitted incident severity is critical")
        elif severity == Severity.high:
            score += 2
            reasons.append("the submitted incident severity is high")
        elif severity == Severity.medium:
            score += 1

        if score >= 8:
            level = RiskLevel.critical
        elif score >= 5:
            level = RiskLevel.high
        elif score >= 2:
            level = RiskLevel.medium
        else:
            level = RiskLevel.low
        return {"score": score, "risk_level": level.value, "reasons": reasons}


class ToolExecutor:
    def __init__(
        self,
        database: Database,
        registry: ToolRegistry,
        injector: FailureInjector,
        *,
        max_attempts: int,
        timeout_seconds: float,
    ) -> None:
        self.database = database
        self.registry = registry
        self.injector = injector
        self.max_attempts = max_attempts
        self.timeout_seconds = timeout_seconds

    def execute(
        self,
        run_id: str,
        step_id: str,
        tool_name: ToolName,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if tool_name not in self.registry.allowed_tools:
            raise ToolFailure(f"tool is not allowlisted: {tool_name}")
        last_error = "tool failed"
        for attempt in range(1, self.max_attempts + 1):
            started = time.perf_counter()
            result: dict[str, Any] | None = None
            try:
                self.injector.before_call(tool_name.value)
                pool = ThreadPoolExecutor(max_workers=1)
                wait_for_pool = True
                try:
                    future = pool.submit(self.registry.invoke, tool_name, arguments)
                    result = future.result(timeout=self.timeout_seconds)
                except FutureTimeoutError:
                    future.cancel()
                    pool.shutdown(wait=False, cancel_futures=True)
                    wait_for_pool = False
                    raise
                finally:
                    if wait_for_pool:
                        pool.shutdown(wait=True)
                duration_ms = (time.perf_counter() - started) * 1000
                self.database.record_tool_call(
                    run_id,
                    step_id,
                    tool_name.value,
                    arguments,
                    result,
                    "succeeded",
                    attempt,
                    duration_ms,
                    None,
                )
                return result
            except FutureTimeoutError:
                failure = ToolFailure("tool execution timed out", transient=True)
            except ToolFailure as error:
                failure = error
            except Exception as error:  # A tool must fail closed and expose no stack trace.
                failure = ToolFailure(f"tool execution failed: {type(error).__name__}")

            duration_ms = (time.perf_counter() - started) * 1000
            last_error = str(failure)
            self.database.record_tool_call(
                run_id,
                step_id,
                tool_name.value,
                arguments,
                result,
                "failed",
                attempt,
                duration_ms,
                last_error,
            )
            if not failure.transient or attempt == self.max_attempts:
                raise ToolFailure(last_error, transient=failure.transient) from failure
            delay_ms = min(25 * (2 ** (attempt - 1)), 100)
            self.database.add_event(
                run_id,
                "tool_retry_scheduled",
                {"tool_name": tool_name.value, "attempt": attempt, "delay_ms": delay_ms},
            )
            time.sleep(delay_ms / 1000)
        raise ToolFailure(last_error)
