"""Top-level analysis orchestration."""

from __future__ import annotations

from pathlib import Path

from smartjoin.config import (
    DEFAULT_DISTINCT_LOW_CARD_THRESHOLD,
    DEFAULT_NEAR_UNIQUE_THRESHOLD,
    DEFAULT_RETENTION_CONFIDENCE_FLOOR,
    DERIVED_CONF_MULT,
    DERIVED_JOINS_ENABLED,
    DERIVED_MAX_AMBIGUOUS_TARGETS,
    DERIVED_MAX_COLUMNS_PER_TABLE,
    DERIVED_MAX_TRANSFORMS_PER_COLUMN,
    DERIVED_MIN_DISTINCT,
    AnalysisSettings,
    merge_date_caps,
)
from smartjoin.ingestion import load_tables
from smartjoin.joins import find_join_candidates
from smartjoin.keys import discover_keys
from smartjoin.models import AnalysisReport, AnalysisSettingsReport
from smartjoin.profiling import profile_tables


def analyze_path(
    path: Path,
    sample_rows: int = 10_000,
    sample_seed: int = 42,
    max_tables: int | None = None,
    max_columns: int | None = None,
    min_confidence: float = 0.8,
    join_weights: dict[str, float] | None = None,
    xlsx_sheet_map: dict[str, str] | None = None,
    json_flatten_depth: int = 1,
    distinct_low_card_threshold: int = DEFAULT_DISTINCT_LOW_CARD_THRESHOLD,
    near_unique_threshold: float = DEFAULT_NEAR_UNIQUE_THRESHOLD,
    date_caps: dict[str, float] | None = None,
    derived_joins_enabled: bool = DERIVED_JOINS_ENABLED,
    derived_max_transforms_per_column: int = DERIVED_MAX_TRANSFORMS_PER_COLUMN,
    derived_max_columns_per_table: int = DERIVED_MAX_COLUMNS_PER_TABLE,
    derived_min_distinct: int = DERIVED_MIN_DISTINCT,
    derived_max_ambiguous_targets: int = DERIVED_MAX_AMBIGUOUS_TARGETS,
    derived_conf_mult: float = DERIVED_CONF_MULT,
    fast_profile: bool = False,
    profile_entropy_cap: int = 50_000,
    retention_confidence_floor: float = DEFAULT_RETENTION_CONFIDENCE_FLOOR,
) -> AnalysisReport:
    """Run ingestion + profiling + key discovery + join discovery."""
    resolved_retention_floor = max(0.0, min(1.0, float(retention_confidence_floor)))
    settings = AnalysisSettings(
        min_confidence=min_confidence,
        retention_confidence_floor=resolved_retention_floor,
        sample_rows=sample_rows,
        sample_seed=sample_seed,
        distinct_low_card_threshold=distinct_low_card_threshold,
        near_unique_threshold=near_unique_threshold,
        date_caps=merge_date_caps(date_caps),
        derived_joins_enabled=derived_joins_enabled,
        derived_max_transforms_per_column=derived_max_transforms_per_column,
        derived_max_columns_per_table=derived_max_columns_per_table,
        derived_min_distinct=derived_min_distinct,
        derived_max_ambiguous_targets=derived_max_ambiguous_targets,
        derived_conf_mult=derived_conf_mult,
    )
    tables = load_tables(
        path=path,
        max_tables=max_tables,
        xlsx_sheet_map=xlsx_sheet_map,
        json_flatten_depth=json_flatten_depth,
        max_columns=max_columns,
    )
    if len(tables) == 0:
        raise ValueError("No supported data files found to analyze.")

    table_profiles = profile_tables(
        tables=tables,
        near_unique_threshold=settings.near_unique_threshold,
        fast_mode=fast_profile,
        entropy_value_cap=profile_entropy_cap,
    )
    keys = discover_keys(
        tables=tables,
        near_unique_seed_threshold=settings.near_unique_threshold,
    )
    joins = find_join_candidates(
        tables=tables,
        sample_rows=settings.sample_rows,
        sample_seed=settings.sample_seed,
        retention_confidence_floor=settings.retention_confidence_floor,
        weights=join_weights,
        near_unique_threshold=settings.near_unique_threshold,
        distinct_low_card_threshold=settings.distinct_low_card_threshold,
        date_caps=settings.date_caps,
        derived_joins_enabled=settings.derived_joins_enabled,
        derived_max_transforms_per_column=settings.derived_max_transforms_per_column,
        derived_max_columns_per_table=settings.derived_max_columns_per_table,
        derived_min_distinct=settings.derived_min_distinct,
        derived_max_ambiguous_targets=settings.derived_max_ambiguous_targets,
        derived_conf_mult=settings.derived_conf_mult,
    )

    return AnalysisReport(
        source_path=str(path.resolve()),
        settings=AnalysisSettingsReport.model_validate(settings.to_report_dict()),
        tables=table_profiles,
        keys=keys,
        joins=joins,
    )
