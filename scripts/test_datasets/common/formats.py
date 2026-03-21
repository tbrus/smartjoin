"""Helpers for deterministic table-level format mixing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

import polars as pl

TARGET_NON_CSV_EXTENSIONS: Final[tuple[str, ...]] = (".parquet", ".json", ".xlsx")


def _read_csv_for_conversion(path: Path) -> pl.DataFrame:
    """Read CSV with a resilient fallback for stricter parser versions."""
    try:
        return pl.read_csv(path, infer_schema_length=1000)
    except Exception:
        try:
            return pl.read_csv(path, infer_schema=False)
        except TypeError:
            # Older Polars versions may not expose `infer_schema`.
            return pl.read_csv(path, infer_schema_length=0)


def _read_manifest(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _table_row_count(table_name: str, row_counts: dict[str, int]) -> int:
    value = row_counts.get(table_name)
    if isinstance(value, int):
        return value
    return 10**18


def _pick_conversions(csv_files: list[Path], row_counts: dict[str, int]) -> dict[str, str]:
    """Choose which CSV tables should be converted to non-CSV formats."""
    if len(csv_files) <= 1:
        return {}

    ranked = sorted(
        csv_files,
        key=lambda path: (_table_row_count(path.stem, row_counts), path.name.lower()),
    )
    max_conversions = min(len(csv_files) - 1, len(TARGET_NON_CSV_EXTENSIONS))

    conversions: dict[str, str] = {}
    for index in range(max_conversions):
        conversions[ranked[index].stem] = TARGET_NON_CSV_EXTENSIONS[index]
    return conversions


def _write_json(path: Path, frame: pl.DataFrame) -> None:
    path.write_text(json.dumps(frame.to_dicts(), indent=2), encoding="utf-8")


def _write_xlsx(path: Path, frame: pl.DataFrame) -> None:
    try:
        import pandas as pd
    except Exception:
        pd = None

    if pd is not None:
        try:
            with pd.ExcelWriter(path, engine="openpyxl") as writer:
                pd.DataFrame(frame.to_dicts()).to_excel(writer, index=False, sheet_name="Data")
            return
        except Exception:
            # Fall back to direct openpyxl writing if pandas/openpyxl interop fails.
            pass

    # Fallback path keeps conversion available even without pandas.
    from openpyxl import Workbook

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Data"
    worksheet.append(list(frame.columns))
    for row in frame.iter_rows():
        worksheet.append(list(row))
    workbook.save(path)


def _convert_csv(path: Path, target_ext: str) -> Path:
    frame = _read_csv_for_conversion(path)
    out_path = path.with_suffix(target_ext)
    if out_path.exists():
        out_path.unlink()
    if target_ext == ".parquet":
        frame.write_parquet(out_path)
    elif target_ext == ".json":
        _write_json(out_path, frame)
    elif target_ext == ".xlsx":
        _write_xlsx(out_path, frame)
    else:  # pragma: no cover
        raise ValueError(f"Unsupported target extension: {target_ext}")
    path.unlink()
    return out_path


def _rewrite_manifest_core_table_files(manifest_path: Path, table_files: dict[str, str]) -> None:
    manifest = _read_manifest(manifest_path)
    if not manifest:
        return
    ground_truth = manifest.get("ground_truth")
    if not isinstance(ground_truth, dict):
        return
    core_tables = ground_truth.get("core_tables")
    if not isinstance(core_tables, list):
        return

    changed = False
    for spec in core_tables:
        if not isinstance(spec, dict):
            continue
        table = spec.get("table")
        if not isinstance(table, str):
            continue
        filename = table_files.get(table)
        if not filename:
            continue
        if spec.get("file") != filename:
            spec["file"] = filename
            changed = True
    if changed:
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def apply_mixed_table_formats(out_dir: Path) -> dict[str, str]:
    """Convert a subset of generated CSV files so domains contain mixed table formats."""
    csv_files = sorted(
        [path for path in out_dir.iterdir() if path.is_file() and path.suffix.lower() == ".csv"],
        key=lambda path: path.name.lower(),
    )
    manifest_path = out_dir / "manifest.json"
    manifest = _read_manifest(manifest_path)
    row_counts = manifest.get("row_counts", {}) if isinstance(manifest, dict) else {}
    if not isinstance(row_counts, dict):
        row_counts = {}

    conversions = _pick_conversions(csv_files, row_counts)
    if not conversions:
        return {path.stem: path.name for path in csv_files}

    table_files: dict[str, str] = {}
    for csv_path in csv_files:
        table_name = csv_path.stem
        target_ext = conversions.get(table_name)
        if target_ext is None:
            table_files[table_name] = csv_path.name
            continue
        new_path = _convert_csv(csv_path, target_ext)
        table_files[table_name] = new_path.name

    _rewrite_manifest_core_table_files(manifest_path, table_files)
    return table_files
