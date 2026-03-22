from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from smartjoin.ingestion import load_tables


def test_load_tables_supports_csv_parquet_and_json(tmp_path: Path) -> None:
    pl.DataFrame({"id": [1, 2], "name": ["a", "b"]}).write_csv(tmp_path / "a.csv")
    pl.DataFrame({"id": [10, 20], "value": [1.5, 2.5]}).write_parquet(tmp_path / "b.parquet")
    (tmp_path / "c.json").write_text(
        json.dumps([{"orderId": "O1", "meta": {"status": "paid"}}]),
        encoding="utf-8",
    )

    tables = load_tables(tmp_path)
    by_name = {table.name: table for table in tables}

    assert set(by_name.keys()) == {"a", "b", "c"}
    assert by_name["a"].metadata["format"] == "csv"
    assert by_name["b"].metadata["format"] == "parquet"
    assert by_name["c"].metadata["format"] == "json"
    assert "meta__status" in by_name["c"].df.columns


def test_load_tables_csv_with_late_float_value_falls_back_to_full_inference(tmp_path: Path) -> None:
    csv_path = tmp_path / "late_types.csv"
    lines = ["Turbo standard", *[str(index) for index in range(1000)], "1957.5"]
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    tables = load_tables(tmp_path)
    by_name = {table.name: table for table in tables}

    assert "late_types" in by_name
    values = by_name["late_types"].df["Turbo standard"].to_list()
    assert len(values) == 1001
    assert float(values[-1]) == pytest.approx(1957.5)


def test_load_tables_supports_xlsx(tmp_path: Path) -> None:
    pd = pytest.importorskip("pandas")
    pytest.importorskip("openpyxl")

    frame = pd.DataFrame({"id": [1, 2], "region": ["R01", "R02"]})
    xlsx_path = tmp_path / "book.xlsx"
    frame.to_excel(xlsx_path, index=False, sheet_name="Data")

    tables = load_tables(tmp_path, xlsx_sheet_map={"book.xlsx": "Data"})
    by_name = {table.name: table for table in tables}
    assert "book" in by_name
    assert by_name["book"].metadata["format"] == "xlsx"
    assert by_name["book"].metadata["sheet"] == "Data"
    assert by_name["book"].df.height == 2


def test_load_tables_scans_supported_files_recursively(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({"id": [1, 2]}).write_csv(nested / "nested.csv")
    pl.DataFrame({"id": [3, 4]}).write_parquet(tmp_path / "top.parquet")

    tables = load_tables(tmp_path)
    by_name = {table.name: table for table in tables}

    assert "nested" in by_name
    assert "top" in by_name


def test_load_tables_reads_all_xlsx_sheets_by_default(tmp_path: Path) -> None:
    pd = pytest.importorskip("pandas")
    pytest.importorskip("openpyxl")

    xlsx_path = tmp_path / "multi.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        pd.DataFrame({"id": [1], "region": ["R01"]}).to_excel(
            writer,
            index=False,
            sheet_name="Data",
        )
        pd.DataFrame({"id": [2], "status": ["active"]}).to_excel(
            writer,
            index=False,
            sheet_name="Archive Rows",
        )

    tables = load_tables(tmp_path)
    by_name = {table.name: table for table in tables}

    assert "multi__Data" in by_name
    assert "multi__Archive_Rows" in by_name
    assert by_name["multi__Data"].metadata["sheet"] == "Data"
    assert by_name["multi__Archive_Rows"].metadata["sheet"] == "Archive Rows"


def test_load_tables_xlsx_sheet_map_selects_single_sheet(tmp_path: Path) -> None:
    pd = pytest.importorskip("pandas")
    pytest.importorskip("openpyxl")

    xlsx_path = tmp_path / "multi.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        pd.DataFrame({"id": [1]}).to_excel(writer, index=False, sheet_name="Data")
        pd.DataFrame({"id": [2]}).to_excel(writer, index=False, sheet_name="Archive")

    tables = load_tables(tmp_path, xlsx_sheet_map={"multi.xlsx": "Archive"})
    by_name = {table.name: table for table in tables}

    assert set(by_name.keys()) == {"multi"}
    assert by_name["multi"].metadata["sheet"] == "Archive"
    assert by_name["multi"].df.to_dicts() == [{"id": 2}]
