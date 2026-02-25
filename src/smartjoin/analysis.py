"""Top-level analysis orchestration."""

from __future__ import annotations

from pathlib import Path

from smartjoin.config import (
    DEFAULT_DISTINCT_LOW_CARD_THRESHOLD,
    DEFAULT_NEAR_UNIQUE_THRESHOLD,
    DERIVED_JOINS_ENABLED,
    DERIVED_CONF_MULT,
    DERIVED_MAX_AMBIGUOUS_TARGETS,
    DERIVED_MAX_COLUMNS_PER_TABLE,
    DERIVED_MAX_TRANSFORMS_PER_COLUMN,
    DERIVED_MIN_DISTINCT,
    AnalysisSettings,
    merge_date_caps,
)
from smartjoin.exporters import build_sql_skeleton
from smartjoin.graphing import build_join_graph, graph_to_report
from smartjoin.ingestion import load_tables
from smartjoin.joins import find_join_candidates
from smartjoin.keys import discover_keys
from smartjoin.models import AnalysisReport, AnalysisSettingsReport, JoinGraphReport
from smartjoin.profiling import profile_tables
from smartjoin.semantics import apply_semantics_plugin


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
    graph_top_k_per_pair: int = 3,
    top_k_edges: int | None = None,
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
    llm_enabled: bool = False,
    llm_plugin: str | None = None,
) -> AnalysisReport:
    """Run ingestion + profiling + key discovery + join discovery + graph build."""
    resolved_top_k_edges = top_k_edges if top_k_edges is not None else graph_top_k_per_pair
    settings = AnalysisSettings(
        min_confidence=min_confidence,
        top_k_edges=max(1, resolved_top_k_edges),
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
        min_confidence=settings.min_confidence,
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
    joins = apply_semantics_plugin(
        candidates=joins,
        llm_enabled=llm_enabled,
        plugin_path=llm_plugin,
    )

    graph = build_join_graph(
        tables=tables,
        joins=joins,
        min_confidence=settings.min_confidence,
        top_k_per_pair=settings.top_k_edges,
    )
    graph_report = graph_to_report(
        graph=graph,
        top_k_per_pair=settings.top_k_edges,
        min_confidence=settings.min_confidence,
    )

    return AnalysisReport(
        source_path=str(path.resolve()),
        settings=AnalysisSettingsReport.model_validate(settings.to_report_dict()),
        tables=table_profiles,
        keys=keys,
        joins=joins,
        graph=graph_report,
    )


def build_graph_report(
    path: Path,
    min_confidence: float = 0.8,
    sample_rows: int = 10_000,
    sample_seed: int = 42,
    max_tables: int | None = None,
    max_columns: int | None = None,
    join_weights: dict[str, float] | None = None,
    xlsx_sheet_map: dict[str, str] | None = None,
    json_flatten_depth: int = 1,
    graph_top_k_per_pair: int = 3,
    top_k_edges: int | None = None,
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
    llm_enabled: bool = False,
    llm_plugin: str | None = None,
) -> JoinGraphReport:
    """Build only join graph output for CLI graph command."""
    report = analyze_path(
        path=path,
        sample_rows=sample_rows,
        sample_seed=sample_seed,
        max_tables=max_tables,
        max_columns=max_columns,
        min_confidence=min_confidence,
        join_weights=join_weights,
        xlsx_sheet_map=xlsx_sheet_map,
        json_flatten_depth=json_flatten_depth,
        graph_top_k_per_pair=graph_top_k_per_pair,
        top_k_edges=top_k_edges,
        distinct_low_card_threshold=distinct_low_card_threshold,
        near_unique_threshold=near_unique_threshold,
        date_caps=date_caps,
        derived_joins_enabled=derived_joins_enabled,
        derived_max_transforms_per_column=derived_max_transforms_per_column,
        derived_max_columns_per_table=derived_max_columns_per_table,
        derived_min_distinct=derived_min_distinct,
        derived_max_ambiguous_targets=derived_max_ambiguous_targets,
        derived_conf_mult=derived_conf_mult,
        fast_profile=fast_profile,
        profile_entropy_cap=profile_entropy_cap,
        llm_enabled=llm_enabled,
        llm_plugin=llm_plugin,
    )
    return report.graph


def export_sql(
    path: Path,
    max_tables: int | None = None,
    max_columns: int | None = None,
    xlsx_sheet_map: dict[str, str] | None = None,
    json_flatten_depth: int = 1,
) -> str:
    """Generate SQL skeleton from inferred table schemas and key candidates."""
    tables = load_tables(
        path=path,
        max_tables=max_tables,
        max_columns=max_columns,
        xlsx_sheet_map=xlsx_sheet_map,
        json_flatten_depth=json_flatten_depth,
    )
    if len(tables) == 0:
        raise ValueError("No supported data files found for SQL export.")
    keys = discover_keys(tables=tables)
    return build_sql_skeleton(tables=tables, keys=keys)
