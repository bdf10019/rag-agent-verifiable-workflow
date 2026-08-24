from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .database import (
    Database,
    IdempotencyConflictError,
    InvalidTransitionError,
)
from .demo import demo_requests
from .models import ApprovalDecision, IncidentRequest, RunView
from .orchestrator import WorkflowOrchestrator
from .settings import Settings


@dataclass(frozen=True)
class Principal:
    username: str
    role: str


DEMO_USERS = {
    "admin": Principal("admin", "admin"),
    "operator": Principal("operator", "operator"),
    "reviewer": Principal("reviewer", "reviewer"),
    "viewer": Principal("viewer", "viewer"),
}


def get_principal(x_demo_user: Annotated[str, Header()] = "viewer") -> Principal:
    principal = DEMO_USERS.get(x_demo_user)
    if not principal:
        raise HTTPException(status_code=401, detail="unknown local demo user")
    return principal


def require_roles(*roles: str) -> Callable[[Principal], Principal]:
    def dependency(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        if principal.role not in roles:
            raise HTTPException(status_code=403, detail="role is not allowed for this operation")
        return principal

    return dependency


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = (settings or Settings()).normalized()
    database = Database(Path(runtime_settings.database_path))
    database.initialize()
    database.seed_demo_data(Path(runtime_settings.sop_directory))
    orchestrator = WorkflowOrchestrator(database, runtime_settings)

    app = FastAPI(
        title="RAG Agent Verifiable Workflow",
        version="1.0.0",
        description=(
            "Offline-first operational incident workflow with allowlisted tools, "
            "evidence verification, retry, audit events, and human approval."
        ),
    )
    app.state.database = database
    app.state.orchestrator = orchestrator
    app.state.settings = runtime_settings

    web_directory = Path(__file__).resolve().parent / "web"
    app.mount("/static", StaticFiles(directory=web_directory), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(web_directory / "index.html")

    @app.get("/healthz", tags=["operations"])
    def health() -> dict[str, Any]:
        metrics = database.metrics()
        return {
            "status": "ok",
            "time": datetime.now(UTC).isoformat(),
            "database": str(Path(runtime_settings.database_path).name),
            "runs_total": metrics["runs_total"],
        }

    @app.get("/readyz", tags=["operations"])
    def readiness() -> dict[str, str]:
        with database.connect() as connection:
            connection.execute("SELECT 1").fetchone()
        return {"status": "ready"}

    @app.get("/metrics", response_class=PlainTextResponse, tags=["operations"])
    def prometheus_metrics() -> str:
        metrics = database.metrics()
        lines = [
            "# HELP opsflow_runs_total Total workflow runs.",
            "# TYPE opsflow_runs_total gauge",
            f"opsflow_runs_total {metrics['runs_total']}",
        ]
        for run_status, count in sorted(metrics["runs_by_status"].items()):
            lines.append(f'opsflow_runs_by_status{{status="{run_status}"}} {count}')
        for tool_status, values in sorted(metrics["tool_calls"].items()):
            lines.append(f'opsflow_tool_calls_total{{status="{tool_status}"}} {values["count"]}')
            lines.append(
                f'opsflow_tool_call_average_ms{{status="{tool_status}"}} {values["average_ms"]:.3f}'
            )
        return "\n".join(lines) + "\n"

    @app.get("/api/v1/demo-requests", tags=["demo"])
    def get_demo_requests() -> dict[str, dict[str, Any]]:
        return demo_requests()

    @app.post("/api/v1/runs", response_model=RunView, tags=["workflow"])
    def create_run(
        request: IncidentRequest,
        _principal: Annotated[Principal, Depends(require_roles("admin", "operator"))],
    ) -> RunView:
        try:
            return orchestrator.submit(request)
        except IdempotencyConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/api/v1/runs", response_model=list[RunView], tags=["workflow"])
    def list_runs(
        _principal: Annotated[
            Principal, Depends(require_roles("admin", "operator", "reviewer", "viewer"))
        ],
        limit: Annotated[int, Query(ge=1, le=100)] = 30,
    ) -> list[RunView]:
        return database.list_runs(limit)

    @app.get("/api/v1/runs/{run_id}", response_model=RunView, tags=["workflow"])
    def get_run(
        run_id: str,
        _principal: Annotated[
            Principal, Depends(require_roles("admin", "operator", "reviewer", "viewer"))
        ],
    ) -> RunView:
        try:
            return database.get_run(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="run not found") from error

    @app.post("/api/v1/runs/{run_id}/resume", response_model=RunView, tags=["workflow"])
    def resume_run(
        run_id: str,
        _principal: Annotated[Principal, Depends(require_roles("admin", "operator"))],
    ) -> RunView:
        try:
            return orchestrator.resume(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="run not found") from error
        except InvalidTransitionError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/api/v1/runs/{run_id}/approval",
        response_model=RunView,
        tags=["workflow"],
    )
    def decide_run(
        run_id: str,
        decision: ApprovalDecision,
        principal: Annotated[Principal, Depends(require_roles("admin", "reviewer"))],
    ) -> RunView:
        try:
            return database.decide_approval(
                run_id,
                principal.username,
                decision.decision,
                decision.note,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="run not found") from error
        except InvalidTransitionError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/api/v1/metrics", tags=["operations"])
    def json_metrics(
        _principal: Annotated[Principal, Depends(require_roles("admin", "operator", "reviewer"))],
    ) -> dict[str, Any]:
        return database.metrics()

    return app
