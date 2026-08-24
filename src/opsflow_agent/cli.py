from __future__ import annotations

import argparse
import json
import platform
import sys
import uuid
from pathlib import Path
from typing import Any

from . import __version__
from .data_import import import_ai4i_csv
from .database import Database
from .demo import demo_requests
from .evaluation import evaluate_cases
from .models import IncidentRequest
from .orchestrator import WorkflowOrchestrator
from .settings import PROJECT_ROOT, Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opsflow",
        description="Run the offline-first verifiable RAG agent workflow.",
    )
    parser.add_argument("--database", type=Path, help="Override the SQLite database path.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="Check local runtime and seed data.")
    subparsers.add_parser("init-db", help="Initialize and seed the local database.")

    demo_parser = subparsers.add_parser("run-demo", help="Execute a deterministic demo case.")
    demo_parser.add_argument("--scenario", choices=["critical", "normal"], default="critical")

    evaluate_parser = subparsers.add_parser("evaluate", help="Run the offline acceptance suite.")
    evaluate_parser.add_argument(
        "--cases",
        type=Path,
        default=PROJECT_ROOT / "examples" / "evals" / "cases.jsonl",
    )
    evaluate_parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "outputs" / "evaluation-report.json",
    )

    import_parser = subparsers.add_parser("import-ai4i", help="Import a downloaded AI4I CSV.")
    import_parser.add_argument("csv_path", type=Path)

    serve_parser = subparsers.add_parser("serve", help="Start the API and local dashboard.")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    return parser


def runtime(args: argparse.Namespace) -> tuple[Settings, Database, WorkflowOrchestrator]:
    settings = Settings().normalized()
    if args.database:
        path = args.database if args.database.is_absolute() else PROJECT_ROOT / args.database
        settings = settings.model_copy(update={"database_path": path})
    database = Database(Path(settings.database_path))
    database.initialize()
    database.seed_demo_data(Path(settings.sop_directory))
    return settings, database, WorkflowOrchestrator(database, settings)


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings, database, orchestrator = runtime(args)

    if args.command == "doctor":
        seed = database.seed_demo_data(Path(settings.sop_directory))
        print_json(
            {
                "status": "ok",
                "version": __version__,
                "python": platform.python_version(),
                "platform": platform.system(),
                "database": Path(settings.database_path).name,
                "seed": seed,
                "allowed_tools": [
                    "lookup_telemetry",
                    "lookup_maintenance_history",
                    "search_sop",
                    "calculate_risk",
                ],
                "external_api_required": False,
            }
        )
        return 0

    if args.command == "init-db":
        print_json(database.seed_demo_data(Path(settings.sop_directory)))
        return 0

    if args.command == "run-demo":
        payload = dict(demo_requests()[args.scenario])
        payload["idempotency_key"] = f"cli-{args.scenario}-{uuid.uuid4().hex[:12]}"
        run = orchestrator.submit(IncidentRequest.model_validate(payload))
        print(run.model_dump_json(indent=2))
        return 0 if run.status.value in {"completed", "needs_review"} else 1

    if args.command == "evaluate":
        report = evaluate_cases(orchestrator, args.cases, args.output)
        print_json(report)
        return 0 if report["failed"] == 0 else 1

    if args.command == "import-ai4i":
        print_json(import_ai4i_csv(database, args.csv_path))
        return 0

    if args.command == "serve":
        import uvicorn

        from .api import create_app

        uvicorn.run(create_app(settings), host=args.host, port=args.port)
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
