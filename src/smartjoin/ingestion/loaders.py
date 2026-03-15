"""Multi-format discovery and loading utilities."""

from __future__ import annotations

import json
import re
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
        [p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS],
        key=lambda p: str(p.relative_to(path)).lower(),
    )
    if max_tables is not None:
        files = files[:max_tables]
    return files


def _load_csv(path: Path) -> pl.DataFrame:
    return pl.read_csv(path, infer_schema_length=1000)


def _load_parquet(path: Path) -> pl.DataFrame:
    return pl.read_parquet(path)


def _normalize_pandas_frame(frame: Any) -> pl.DataFrame:
    """Normalize a pandas DataFrame for stable Polars ingestion."""
    import pandas as pd

    normalized: dict[str, list[Any]] = {}
    for col_name in frame.columns:
        series = frame[col_name].where(frame[col_name].notna(), None)
        values = series.tolist()
        if pd.api.types.is_datetime64_any_dtype(series) or pd.api.types.is_timedelta64_dtype(
            series
        ):
            normalized[col_name] = [None if value is None else str(value) for value in values]
            continue
        if pd.api.types.is_object_dtype(series):
            non_null_types = {type(value) for value in values if value is not None}
            if len(non_null_types) > 1:
                normalized[col_name] = [None if value is None else str(value) for value in values]
                continue
        normalized[col_name] = values
    return pl.DataFrame(normalized, strict=False)


def _load_xlsx(path: Path, sheet_name: str | None = None) -> list[tuple[str, pl.DataFrame]]:
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover - handled via runtime dependency
        raise ValueError("XLSX support requires pandas/openpyxl installed.") from exc

    # No explicit sheet means read all workbook sheets.
    target_sheet: str | None = sheet_name if sheet_name is not None else None
    loaded = pd.read_excel(path, sheet_name=target_sheet)
    if isinstance(loaded, dict):
        return [(str(name), _normalize_pandas_frame(frame)) for name, frame in loaded.items()]
    resolved = str(sheet_name if sheet_name is not None else 0)
    return [(resolved, _normalize_pandas_frame(loaded))]


def _sanitize_sheet_name(sheet_name: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_]+", "_", sheet_name.strip())
    token = re.sub(r"_+", "_", token).strip("_")
    return token or "sheet"


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
            table_name = file_path.stem
        elif suffix == ".parquet":
            df = _load_parquet(file_path)
            table_name = file_path.stem
        elif suffix == ".xlsx":
            requested_sheet = None
            if xlsx_sheet_map and file_path.name in xlsx_sheet_map:
                requested_sheet = xlsx_sheet_map[file_path.name]
            sheet_frames = _load_xlsx(file_path, sheet_name=requested_sheet)
            use_sheet_suffix = requested_sheet is None and len(sheet_frames) > 1
            for sheet, sheet_df in sheet_frames:
                sheet_meta = dict(metadata)
                sheet_meta["sheet"] = sheet
                if max_columns is not None:
                    selected_cols = sheet_df.columns[:max_columns]
                    sheet_df = sheet_df.select(selected_cols)
                    sheet_meta["max_columns_applied"] = max_columns
                sheet_suffix = _sanitize_sheet_name(sheet)
                table_name = (
                    f"{file_path.stem}__{sheet_suffix}" if use_sheet_suffix else file_path.stem
                )
                tables.append(
                    Table(
                        name=table_name,
                        df=sheet_df,
                        path=file_path,
                        metadata=sheet_meta,
                    )
                )
            continue
        elif suffix == ".json":
            metadata["flatten_depth"] = json_flatten_depth
            df = _load_json(file_path, flatten_depth=json_flatten_depth)
            table_name = file_path.stem
        else:  # pragma: no cover
            continue

        if max_columns is not None:
            selected_cols = df.columns[:max_columns]
            df = df.select(selected_cols)
            metadata["max_columns_applied"] = max_columns

        tables.append(
            Table(
                name=table_name,
                df=df,
                path=file_path,
                metadata=metadata,
            )
        )

    return tables
