"""Multi-format discovery and loading utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl

from smartjoin.models import Table

SUPPORTED_EXTENSIONS = {".csv", ".parquet", ".xlsx", ".json"}
DEFAULT_EXCLUDED_STEMS = {"manifest", "report", "graph"}


def _flatten_dict(payload: dict[str, Any], max_depth: int = 1, prefix: str = "") -> dict[str, Any]:
    """Flatten nested dictionaries up to a bounded depth."""
    out: dict[str, Any] = {}
    for key in sorted(payload.keys()):
        value = payload[key]
        out_key = f"{prefix}{key}" if not prefix else f"{prefix}__{key}"
        if isinstance(value, dict) and max_depth > 0:
            out.update(_flatten_dict(value, max_depth=max_depth - 1, prefix=out_key))
            continue
        if isinstance(value, dict):
            out[out_key] = json.dumps(value, sort_keys=True)
            continue
        if isinstance(value, (list, tuple)):
            out[out_key] = json.dumps(value, sort_keys=True)
            continue
        out[out_key] = value
    return out


def discover_data_files(path: Path, max_tables: int | None = None) -> list[Path]:
    """Return sorted supported data files under a directory."""
    if path.is_file():
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type: {path.suffix}. "
                f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )
        return [path]

    files = sorted(
        [p for p in path.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS],
        key=lambda p: p.name.lower(),
    )
    if max_tables is not None:
        files = files[:max_tables]
    return files


def _load_csv(path: Path) -> pl.DataFrame:
    return pl.read_csv(path, infer_schema_length=1000)


def _load_parquet(path: Path) -> pl.DataFrame:
    return pl.read_parquet(path)


def _load_xlsx(path: Path, sheet_name: str | None = None) -> pl.DataFrame:
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover - handled via runtime dependency
        raise ValueError("XLSX support requires pandas/openpyxl installed.") from exc

    target_sheet = sheet_name if sheet_name is not None else 0
    frame = pd.read_excel(path, sheet_name=target_sheet)
    # Excel sheets often contain mixed-type object columns (text + blanks + temporal values).
    # Build columns explicitly and coerce ambiguous object/temporal data to string for stability.
    normalized: dict[str, list[Any]] = {}
    for col_name in frame.columns:
        series = frame[col_name].where(frame[col_name].notna(), None)
        values = series.tolist()
        if pd.api.types.is_datetime64_any_dtype(series) or pd.api.types.is_timedelta64_dtype(series):
            normalized[col_name] = [None if value is None else str(value) for value in values]
            continue
        if pd.api.types.is_object_dtype(series):
            non_null_types = {type(value) for value in values if value is not None}
            if len(non_null_types) > 1:
                normalized[col_name] = [None if value is None else str(value) for value in values]
                continue
        normalized[col_name] = values
    return pl.DataFrame(normalized, strict=False)


def _load_json(path: Path, flatten_depth: int = 1) -> pl.DataFrame:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    rows: list[dict[str, Any]]
    if isinstance(payload, list):
        rows = []
        for item in payload:
            if isinstance(item, dict):
                rows.append(_flatten_dict(item, max_depth=flatten_depth))
            else:
                rows.append({"value": item})
    elif isinstance(payload, dict):
        rows = [_flatten_dict(payload, max_depth=flatten_depth)]
    else:
        rows = [{"value": payload}]
    return pl.from_dicts(rows)


def load_tables(
    path: Path,
    max_tables: int | None = None,
    xlsx_sheet_map: dict[str, str] | None = None,
    json_flatten_depth: int = 1,
    max_columns: int | None = None,
    exclude_stem_prefixes: set[str] | None = None,
) -> list[Table]:
    """Load discovered supported files into internal `Table` objects."""
    files = discover_data_files(path=path, max_tables=max_tables)
    if path.is_dir():
        excluded = (
            {stem.lower() for stem in DEFAULT_EXCLUDED_STEMS}
            if exclude_stem_prefixes is None
            else {stem.lower() for stem in exclude_stem_prefixes}
        )
        files = [
            file_path
            for file_path in files
            if not any(file_path.stem.lower().startswith(stem) for stem in excluded)
        ]
    tables: list[Table] = []
    for file_path in files:
        suffix = file_path.suffix.lower()
        metadata: dict[str, Any] = {"format": suffix.removeprefix(".")}

        if suffix == ".csv":
            df = _load_csv(file_path)
        elif suffix == ".parquet":
            df = _load_parquet(file_path)
        elif suffix == ".xlsx":
            sheet_name = None
            if xlsx_sheet_map and file_path.name in xlsx_sheet_map:
                sheet_name = xlsx_sheet_map[file_path.name]
            metadata["sheet"] = sheet_name or 0
            df = _load_xlsx(file_path, sheet_name=sheet_name)
        elif suffix == ".json":
            metadata["flatten_depth"] = json_flatten_depth
            df = _load_json(file_path, flatten_depth=json_flatten_depth)
        else:  # pragma: no cover
            continue

        if max_columns is not None:
            selected_cols = df.columns[:max_columns]
            df = df.select(selected_cols)
            metadata["max_columns_applied"] = max_columns

        tables.append(
            Table(
                name=file_path.stem,
                df=df,
                path=file_path,
                metadata=metadata,
            )
        )

    return tables
