"""Top-level analysis orchestration."""

from __future__ import annotations

from pathlib import Path

from alchemia.exporters import build_sql_skeleton
from alchemia.graphing import build_join_graph, graph_to_report
from alchemia.ingestion import load_tables
from alchemia.joins import find_join_candidates
from alchemia.keys import discover_keys
from alchemia.models import AnalysisReport, JoinGraphReport
from alchemia.profiling import profile_tables
from alchemia.semantics import apply_semantics_plugin


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
    fast_profile: bool = False,
    profile_entropy_cap: int = 50_000,
    llm_enabled: bool = False,
    llm_plugin: str | None = None,
) -> AnalysisReport:
    """Run ingestion + profiling + key discovery + join discovery + graph build."""
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
        fast_mode=fast_profile,
        entropy_value_cap=profile_entropy_cap,
    )
    keys = discover_keys(tables=tables)
    joins = find_join_candidates(
        tables=tables,
        sample_rows=sample_rows,
        sample_seed=sample_seed,
        min_confidence=min_confidence,
        weights=join_weights,
    )
    joins = apply_semantics_plugin(
        candidates=joins,
        llm_enabled=llm_enabled,
        plugin_path=llm_plugin,
    )

    graph = build_join_graph(
        tables=tables,
        joins=joins,
        min_confidence=min_confidence,
        top_k_per_pair=graph_top_k_per_pair,
    )
    graph_report = graph_to_report(graph)

    return AnalysisReport(
        source_path=str(path.resolve()),
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
