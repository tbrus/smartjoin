from pathlib import Path

import polars as pl
import pytest

from alchemia.models import Table
from alchemia.profiling import profile_table


def test_profile_table_computes_expected_column_stats() -> None:
    table = Table(
        name="people",
        path=Path("people.csv"),
        df=pl.DataFrame(
            {
                "id": [1, 2, 2, None],
                "city": ["NY", "SF", None, "NY"],
            }
        ),
    )

    result = profile_table(table, sample_values_limit=3)
    by_name = {column.name: column for column in result.columns}

    assert result.table_name == "people"
    assert result.row_count == 4
    assert result.duplicate_row_count == 0
    assert result.duplicate_row_pct == pytest.approx(0.0)
    assert result.candidate_unique_columns == []
    assert result.near_unique_columns == []

    assert by_name["id"].distinct_count == 2
    assert by_name["id"].null_pct == pytest.approx(0.25)
    assert by_name["id"].unique_ratio == pytest.approx(2 / 3)
    assert by_name["id"].near_unique is False
    assert by_name["id"].entropy > 0.0
    assert by_name["id"].sample_values == [1, 2]

    assert by_name["city"].distinct_count == 2
    assert by_name["city"].null_pct == pytest.approx(0.25)
    assert by_name["city"].unique_ratio == pytest.approx(2 / 3)
    assert by_name["city"].near_unique is False
    assert by_name["city"].entropy > 0.0
    assert by_name["city"].sample_values == ["NY", "SF"]


def test_profile_table_marks_near_unique_and_supports_fast_mode() -> None:
    table = Table(
        name="orders",
        path=Path("orders.csv"),
        df=pl.DataFrame(
            {
                "order_id": [1, 2, 3, 4, 5, 5],
                "status": ["new", "new", "paid", "paid", "paid", "paid"],
            }
        ),
    )

    result = profile_table(
        table,
        near_unique_threshold=0.8,
        compute_entropy=False,
        compute_duplicate_rows=False,
    )
    by_name = {column.name: column for column in result.columns}

    assert "order_id" in result.near_unique_columns
    assert by_name["order_id"].near_unique is True
    assert by_name["order_id"].entropy == 0.0
    assert result.duplicate_row_count == 0
