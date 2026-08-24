from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .database import Database

AI4I_REQUIRED_COLUMNS = {
    "Type",
    "Air temperature [K]",
    "Process temperature [K]",
    "Rotational speed [rpm]",
    "Torque [Nm]",
    "Tool wear [min]",
    "Machine failure",
}


def import_ai4i_csv(database: Database, path: Path) -> dict[str, Any]:
    """Import the public AI4I dataset into a repeatable operational timeline.

    AI4I rows describe product observations rather than a per-asset history. The
    adapter groups them into three demo assets by product type and assigns stable
    minute timestamps in file order. This transformation is documented and does
    not claim that the generated timeline is an original field measurement.
    """

    if not path.is_file():
        raise FileNotFoundError(path)
    start = datetime(2020, 1, 1, tzinfo=UTC)
    inserted = 0
    unchanged = 0
    failures = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or [])
        missing = sorted(AI4I_REQUIRED_COLUMNS - fieldnames)
        if missing:
            raise ValueError(f"AI4I CSV is missing required columns: {', '.join(missing)}")
        with database.connect() as connection:
            for index, row in enumerate(reader):
                product_type = str(row["Type"]).strip().upper()
                if product_type not in {"L", "M", "H"}:
                    raise ValueError(f"unexpected AI4I product type at row {index + 2}")
                observed_at = (start + timedelta(minutes=index)).isoformat()
                failure_modes = [
                    name
                    for name in ("TWF", "HDF", "PWF", "OSF", "RNF")
                    if str(row.get(name, "0")).strip() == "1"
                ]
                machine_failure = int(row["Machine failure"])
                if machine_failure not in {0, 1}:
                    raise ValueError(f"invalid machine failure flag at row {index + 2}")
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO telemetry
                    (asset_id, observed_at, air_temp, process_temp, rpm, torque, tool_wear,
                     machine_failure, failure_mode, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'uci_ai4i_2020')
                    """,
                    (
                        f"AI4I-{product_type}",
                        observed_at,
                        float(row["Air temperature [K]"]),
                        float(row["Process temperature [K]"]),
                        int(row["Rotational speed [rpm]"]),
                        float(row["Torque [Nm]"]),
                        int(row["Tool wear [min]"]),
                        machine_failure,
                        ",".join(failure_modes) or None,
                    ),
                )
                if cursor.rowcount:
                    inserted += 1
                    failures += machine_failure
                else:
                    unchanged += 1
    return {
        "source": "UCI AI4I 2020 Predictive Maintenance Dataset",
        "inserted": inserted,
        "unchanged": unchanged,
        "failure_rows": failures,
        "asset_ids": ["AI4I-L", "AI4I-M", "AI4I-H"],
    }
