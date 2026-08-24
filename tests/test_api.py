from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from opsflow_agent.api import create_app
from opsflow_agent.demo import demo_requests
from opsflow_agent.settings import Settings


def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


def test_health_dashboard_and_metrics(settings: Settings) -> None:
    with client(settings) as value:
        assert value.get("/healthz").json()["status"] == "ok"
        assert value.get("/readyz").json() == {"status": "ready"}
        assert "事件時間（UTC）" in value.get("/").text
        assert ":00Z`" in value.get("/static/app.js").text
        metrics = value.get("/metrics").text
        assert "opsflow_runs_total" in metrics


def test_role_policy_create_and_review(settings: Settings) -> None:
    payload = dict(demo_requests()["critical"])
    payload["idempotency_key"] = "api-critical-001"
    with client(settings) as value:
        forbidden = value.post("/api/v1/runs", json=payload, headers={"X-Demo-User": "viewer"})
        assert forbidden.status_code == 403

        created = value.post("/api/v1/runs", json=payload, headers={"X-Demo-User": "operator"})
        assert created.status_code == 200
        run = created.json()
        assert run["status"] == "needs_review"

        denied = value.post(
            f"/api/v1/runs/{run['run_id']}/approval",
            json={"decision": "approved", "note": "reviewed evidence"},
            headers={"X-Demo-User": "operator"},
        )
        assert denied.status_code == 403

        approved = value.post(
            f"/api/v1/runs/{run['run_id']}/approval",
            json={"decision": "approved", "note": "reviewed evidence"},
            headers={"X-Demo-User": "reviewer"},
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "completed"


def test_idempotency_conflict_is_http_409(settings: Settings) -> None:
    payload = dict(demo_requests()["normal"])
    payload["idempotency_key"] = "api-idempotency-001"
    with client(settings) as value:
        first = value.post("/api/v1/runs", json=payload, headers={"X-Demo-User": "operator"})
        assert first.status_code == 200
        payload["question"] = "A changed question that uses the same key."
        conflict = value.post("/api/v1/runs", json=payload, headers={"X-Demo-User": "operator"})
        assert conflict.status_code == 409


def test_database_name_does_not_expose_absolute_path(settings: Settings) -> None:
    with client(settings) as value:
        response = value.get("/healthz").json()
        assert response["database"] == Path(settings.database_path).name
        assert str(Path(settings.database_path).parent) not in str(response)
