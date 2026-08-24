from __future__ import annotations

from pathlib import Path

from opsflow_agent.data_import import import_ai4i_csv
from opsflow_agent.database import Database

AI4I_SAMPLE = (
    "UDI,Product ID,Type,Air temperature [K],Process temperature [K],"
    "Rotational speed [rpm],Torque [Nm],Tool wear [min],Machine failure,"
    "TWF,HDF,PWF,OSF,RNF\n"
    "1,M14860,M,298.1,308.6,1551,42.8,0,0,0,0,0,0,0\n"
    "2,L47181,L,298.2,308.7,1408,46.3,3,1,0,1,0,0,0\n"
)


def test_ai4i_import_is_repeatable(database: Database, tmp_path: Path) -> None:
    source = tmp_path / "ai4i.csv"
    source.write_text(AI4I_SAMPLE, encoding="utf-8")

    first = import_ai4i_csv(database, source)
    second = import_ai4i_csv(database, source)

    assert first["inserted"] == 2
    assert first["failure_rows"] == 1
    assert second["inserted"] == 0
    assert second["unchanged"] == 2


def test_ai4i_import_rejects_wrong_schema(database: Database, tmp_path: Path) -> None:
    source = tmp_path / "invalid.csv"
    source.write_text("Type,unknown\nL,1\n", encoding="utf-8")

    try:
        import_ai4i_csv(database, source)
    except ValueError as error:
        assert "missing required columns" in str(error)
    else:
        raise AssertionError("invalid schema should fail")
