from __future__ import annotations

from pathlib import Path

import pytest

from opsflow_agent.database import Database
from opsflow_agent.orchestrator import WorkflowOrchestrator
from opsflow_agent.settings import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "test.db",
        sop_directory=Settings().sop_directory,
        max_tool_attempts=3,
        tool_timeout_seconds=2,
    ).normalized()


@pytest.fixture
def database(settings: Settings) -> Database:
    value = Database(Path(settings.database_path))
    value.initialize()
    value.seed_demo_data(Path(settings.sop_directory))
    return value


@pytest.fixture
def orchestrator(database: Database, settings: Settings) -> WorkflowOrchestrator:
    return WorkflowOrchestrator(database, settings)
