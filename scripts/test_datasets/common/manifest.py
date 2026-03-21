"""Shared manifest helpers for test dataset generators."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def expected_joins_from_relationships(relationships: Sequence[Mapping[str, Any]]) -> list[str]:
    """Build canonical expected join strings from core relationships."""
    expected: list[str] = []
    for relationship in relationships:
        from_table = str(relationship.get("from_table", "")).strip()
        from_column = str(relationship.get("from_column", "")).strip()
        to_table = str(relationship.get("to_table", "")).strip()
        to_column = str(relationship.get("to_column", "")).strip()
        if not all([from_table, from_column, to_table, to_column]):
            continue
        expected.append(f"{from_table}.{from_column} -> {to_table}.{to_column}")
    return expected


def build_manifest(
    *,
    generator: str,
    config: dict[str, Any],
    row_counts: dict[str, int],
    ground_truth: dict[str, Any],
    expected_joins: list[str] | None = None,
    trap_columns: list[str] | None = None,
) -> dict[str, Any]:
    """Create a normalized manifest structure shared across all domains."""
    normalized_ground_truth: dict[str, Any] = {
        "core_tables": [],
        "core_relationships": [],
        "composite_key_candidates": [],
        "traps": {},
        "guard_expectations": [],
        "regression_cases": [],
    }
    normalized_ground_truth.update(ground_truth)

    if expected_joins is None:
        core_relationships = normalized_ground_truth.get("core_relationships", [])
        expected_joins = expected_joins_from_relationships(core_relationships)

    return {
        "generator": generator,
        "config": config,
        "row_counts": row_counts,
        "expected_joins": expected_joins,
        "trap_columns": trap_columns or [],
        "ground_truth": normalized_ground_truth,
    }


def write_manifest(out_dir: Path, manifest: dict[str, Any]) -> Path:
    """Write manifest.json and return output path."""
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path
