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
    assert by_name["book"].df.height == 2
