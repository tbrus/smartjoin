"""Basic SQL DDL skeleton generation."""

from __future__ import annotations

import polars as pl

from smartjoin.models import Table, TableKeyDiscovery


def _sql_type(dtype: pl.DataType) -> str:
    if dtype.is_integer():
        return "BIGINT"
    if dtype.is_float():
        return "DOUBLE PRECISION"
    if dtype == pl.Boolean:
        return "BOOLEAN"
    if dtype.is_temporal():
        if dtype == pl.Date:
            return "DATE"
        return "TIMESTAMP"
    return "TEXT"


def _choose_primary_key(discovery: TableKeyDiscovery) -> list[str] | None:
    for candidate in discovery.primary_key_candidates:
        if candidate.score >= 0.99 and candidate.null_row_pct == 0.0:
            return candidate.columns
    for candidate in discovery.composite_key_candidates:
        if candidate.score >= 0.995 and candidate.null_row_pct == 0.0:
            return candidate.columns
    return None


def build_sql_skeleton(tables: list[Table], keys: list[TableKeyDiscovery]) -> str:
    """Generate deterministic SQL CREATE TABLE statements."""
    key_map = {item.table_name: item for item in keys}
    statements: list[str] = []

    for table in sorted(tables, key=lambda t: t.name.lower()):
        lines: list[str] = []
        for column in table.df.columns:
            dtype = table.df.schema[column]
            lines.append(f'  "{column}" {_sql_type(dtype)}')

        discovery = key_map.get(table.name)
        if discovery is not None:
            pk_columns = _choose_primary_key(discovery)
            if pk_columns:
                quoted = ", ".join(f'"{column}"' for column in pk_columns)
                lines.append(f"  PRIMARY KEY ({quoted})")
            else:
                for candidate in discovery.primary_key_candidates[:1]:
                    if candidate.score >= 0.995 and candidate.null_row_pct == 0.0:
                        quoted = ", ".join(f'"{column}"' for column in candidate.columns)
                        lines.append(f"  UNIQUE ({quoted})")
                        break

        statement = "CREATE TABLE " + f'"{table.name}"' + " (\n" + ",\n".join(lines) + "\n);"
        statements.append(statement)

    return "\n\n".join(statements) + "\n"
