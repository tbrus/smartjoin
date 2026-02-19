"""Profiling functions for table and column-level statistics."""

from __future__ import annotations

import math
from typing import Any

import polars as pl

from alchemia.models import ColumnProfile, Table, TableProfile

DEFAULT_NEAR_UNIQUE_THRESHOLD = 0.90
DEFAULT_ENTROPY_VALUE_CAP = 50_000


def _sample_values(series: pl.Series, max_values: int) -> list[Any]:
    """Collect deterministic non-null sample values from a column."""
    return series.drop_nulls().unique(maintain_order=True).head(max_values).to_list()


def _safe_min_max(series: pl.Series) -> tuple[Any, Any]:
    """Return min/max if supported for dtype, else `(None, None)`."""
    try:
        non_null = series.drop_nulls()
        if non_null.len() == 0:
            return None, None
        return non_null.min(), non_null.max()
    except Exception:
        return None, None


def _length_stats(series: pl.Series) -> tuple[float | None, int | None, int | None]:
    """Return average/min/max lengths for string-like representation."""
    non_null = series.drop_nulls()
    if non_null.len() == 0:
        return None, None, None

    try:
        lengths = non_null.cast(pl.String).str.len_chars()
    except Exception:
        return None, None, None

    return float(lengths.mean()), int(lengths.min()), int(lengths.max())


def _entropy(series: pl.Series, value_cap: int = DEFAULT_ENTROPY_VALUE_CAP) -> float:
    """Compute Shannon entropy on non-null values."""
    non_null = series.drop_nulls()
    n = non_null.len()
    if n == 0:
        return 0.0

    if value_cap > 0 and n > value_cap:
        non_null = non_null.head(value_cap)
        n = non_null.len()

    counts = non_null.value_counts(sort=False).get_column("count").to_list()
    entropy = 0.0
    for count in counts:
        p = count / n
        entropy += -p * math.log2(p)
    return float(entropy)


def profile_table(
    table: Table,
    sample_values_limit: int = 5,
    near_unique_threshold: float = DEFAULT_NEAR_UNIQUE_THRESHOLD,
    compute_entropy: bool = True,
    entropy_value_cap: int = DEFAULT_ENTROPY_VALUE_CAP,
    compute_duplicate_rows: bool = True,
) -> TableProfile:
    """Build profile stats for one table."""
    df = table.df
    row_count = df.height
    if row_count == 0 or not compute_duplicate_rows:
        duplicate_row_count = 0
    else:
        duplicate_row_count = row_count - df.unique().height
    duplicate_row_pct = 0.0 if row_count == 0 else duplicate_row_count / row_count

    columns: list[ColumnProfile] = []
    candidate_unique_columns: list[str] = []
    near_unique_columns: list[str] = []

    for column_name in df.columns:
        series = df.get_column(column_name)
        null_count = series.null_count()
        non_null_count = row_count - null_count
        null_pct = 0.0 if row_count == 0 else null_count / row_count
        distinct_count = series.drop_nulls().n_unique()
        unique_ratio = 0.0 if non_null_count == 0 else distinct_count / non_null_count
        near_unique = non_null_count > 0 and unique_ratio >= near_unique_threshold
        min_value, max_value = _safe_min_max(series)
        avg_length, min_length, max_length = _length_stats(series)

        if non_null_count > 0 and distinct_count == non_null_count and null_count == 0:
            candidate_unique_columns.append(column_name)
        if near_unique:
            near_unique_columns.append(column_name)

        columns.append(
            ColumnProfile(
                name=column_name,
                dtype=str(series.dtype),
                null_pct=float(null_pct),
                distinct_count=int(distinct_count),
                unique_ratio=float(unique_ratio),
                near_unique=near_unique,
                entropy=(
                    _entropy(series, value_cap=entropy_value_cap)
                    if compute_entropy
                    else 0.0
                ),
                sample_values=_sample_values(series=series, max_values=sample_values_limit),
                min_value=min_value,
                max_value=max_value,
                avg_length=avg_length,
                min_length=min_length,
                max_length=max_length,
            )
        )

    return TableProfile(
        table_name=table.name,
        row_count=row_count,
        duplicate_row_count=duplicate_row_count,
        duplicate_row_pct=float(duplicate_row_pct),
        candidate_unique_columns=sorted(candidate_unique_columns),
        near_unique_columns=sorted(near_unique_columns),
        columns=columns,
    )


def profile_tables(
    tables: list[Table],
    sample_values_limit: int = 5,
    near_unique_threshold: float = DEFAULT_NEAR_UNIQUE_THRESHOLD,
    compute_entropy: bool = True,
    entropy_value_cap: int = DEFAULT_ENTROPY_VALUE_CAP,
    compute_duplicate_rows: bool = True,
    fast_mode: bool = False,
) -> list[TableProfile]:
    """Profile many tables, sorted for deterministic output."""
    effective_sample_values_limit = sample_values_limit
    effective_compute_entropy = compute_entropy
    effective_compute_duplicate_rows = compute_duplicate_rows
    if fast_mode:
        effective_sample_values_limit = min(sample_values_limit, 3)
        effective_compute_entropy = False
        effective_compute_duplicate_rows = False

    profiles = [
        profile_table(
            table=table,
            sample_values_limit=effective_sample_values_limit,
            near_unique_threshold=near_unique_threshold,
            compute_entropy=effective_compute_entropy,
            entropy_value_cap=entropy_value_cap,
            compute_duplicate_rows=effective_compute_duplicate_rows,
        )
        for table in tables
    ]
    return sorted(profiles, key=lambda p: p.table_name.lower())
