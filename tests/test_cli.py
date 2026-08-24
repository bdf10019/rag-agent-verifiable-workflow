from __future__ import annotations

from pathlib import Path
from typing import Any

import uvicorn

from opsflow_agent.cli import main


def test_serve_passes_selected_database_to_app(tmp_path: Path, monkeypatch: Any) -> None:
    selected = tmp_path / "selected.db"
    captured: dict[str, Any] = {}

    def fake_run(app: Any, *, host: str, port: int) -> None:
        captured.update({"app": app, "host": host, "port": port})

    monkeypatch.setattr(uvicorn, "run", fake_run)
    result = main(
        [
            "--database",
            str(selected),
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            "9876",
        ]
    )

    assert result == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9876
    assert captured["app"].state.settings.database_path == selected
