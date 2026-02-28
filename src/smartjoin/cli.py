"""CLI entrypoint for Smartjoin."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from smartjoin.analysis import analyze_path, build_graph_report, export_sql
from smartjoin.debug_site import build_debug_site

app = typer.Typer(help="Smartjoin: deterministic relational inference engine.")


def _parse_assignments(values: list[str], label: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise typer.BadParameter(f"{label} entries must use key=value format. Got: {item}")
        key, value = item.split("=", maxsplit=1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            raise typer.BadParameter(f"{label} entries must use key=value format. Got: {item}")
        out[key] = value
    return out


def _parse_weight_assignments(values: list[str]) -> dict[str, float]:
    raw = _parse_assignments(values=values, label="join-weight")
    parsed: dict[str, float] = {}
    for key, value in raw.items():
        try:
            parsed[key] = float(value)
        except ValueError as exc:
            raise typer.BadParameter(f"Invalid numeric weight for {key}: {value}") from exc
    return parsed


def _parse_float_assignments_csv(raw: str | None, label: str) -> dict[str, float]:
    if raw is None or not raw.strip():
        return {}
    chunks = [chunk.strip() for chunk in raw.split(",") if chunk.strip()]
    pairs = _parse_assignments(chunks, label=label)
    parsed: dict[str, float] = {}
    for key, value in pairs.items():
        try:
            parsed[key] = float(value)
        except ValueError as exc:
            raise typer.BadParameter(f"Invalid numeric {label} value for {key}: {value}") from exc
    return parsed


@app.callback()
def root() -> None:
    """Top-level CLI group."""


@app.command("analyze")
def analyze_command(
    path: Annotated[Path, typer.Argument(..., exists=True, readable=True, resolve_path=True)],
    format: Annotated[
        str,
        typer.Option(help="Output format. Only 'json' is currently supported."),
    ] = "json",
    out: Annotated[
        Path | None,
        typer.Option(help="Optional output JSON file path."),
    ] = None,
    sample_rows: Annotated[
        int,
        typer.Option(min=1, help="Rows sampled per column for join inference."),
    ] = 10_000,
    sample_seed: Annotated[
        int,
        typer.Option(help="Deterministic seed used for row sampling."),
    ] = 42,
    max_tables: Annotated[
        int | None,
        typer.Option(min=1, help="Maximum files to analyze."),
    ] = None,
    max_columns: Annotated[
        int | None,
        typer.Option(min=1, help="Maximum columns per table to consider."),
    ] = None,
    min_confidence: Annotated[
        float,
        typer.Option(min=0.0, max=1.0, help="Minimum confidence threshold for joins."),
    ] = 0.8,
    top_k_edges: Annotated[
        int,
        typer.Option(
            "--top-k-edges",
            "--graph-top-k-per-pair",
            min=1,
            help="Top K join edges retained per table pair in graph output.",
        ),
    ] = 3,
    distinct_low_card_threshold: Annotated[
        int,
        typer.Option(min=1, help="Distinct-count threshold used for low-cardinality trap guard."),
    ] = 64,
    near_unique_threshold: Annotated[
        float,
        typer.Option(
            min=0.0,
            max=1.0,
            help="Near-unique threshold used in profiling, key seeds, and join pruning.",
        ),
    ] = 0.9,
    date_caps: Annotated[
        str | None,
        typer.Option(
            help=(
                "Date caps override as comma-separated key=value pairs, e.g. "
                "'temporal_overlap=0.6,mixed_temporal=0.75'"
            )
        ),
    ] = None,
    fast_profile: Annotated[
        bool,
        typer.Option(help="Enable faster profiling (skips expensive entropy/duplicate scans)."),
    ] = False,
    profile_entropy_cap: Annotated[
        int,
        typer.Option(min=100, help="Max non-null values used for entropy computation per column."),
    ] = 50_000,
    json_flatten_depth: Annotated[
        int,
        typer.Option(min=0, help="Flatten depth for nested JSON objects."),
    ] = 1,
    join_weight: Annotated[
        list[str] | None,
        typer.Option("--join-weight", help="Override join weight, e.g. jaccard=0.2"),
    ] = None,
    xlsx_sheet: Annotated[
        list[str] | None,
        typer.Option(
            "--xlsx-sheet",
            help="Per-file sheet mapping, e.g. sales.xlsx=Sheet2",
        ),
    ] = None,
) -> None:
    """Analyze a folder of structured files and emit JSON report."""
    if format.lower() != "json":
        raise typer.BadParameter("Only --format json is supported.")

    report = analyze_path(
        path=path,
        sample_rows=sample_rows,
        sample_seed=sample_seed,
        max_tables=max_tables,
        max_columns=max_columns,
        min_confidence=min_confidence,
        top_k_edges=top_k_edges,
        distinct_low_card_threshold=distinct_low_card_threshold,
        near_unique_threshold=near_unique_threshold,
        date_caps=_parse_float_assignments_csv(date_caps, label="date-caps"),
        fast_profile=fast_profile,
        profile_entropy_cap=profile_entropy_cap,
        join_weights=_parse_weight_assignments(join_weight or []),
        xlsx_sheet_map=_parse_assignments(xlsx_sheet or [], label="xlsx-sheet"),
        json_flatten_depth=json_flatten_depth,
    )
    rendered = report.model_dump_json(indent=2)

    if out is None:
        typer.echo(rendered)
        return

    out.write_text(rendered, encoding="utf-8")
    typer.echo(f"Wrote report: {out}")


@app.command("graph")
def graph_command(
    path: Annotated[Path, typer.Argument(..., exists=True, readable=True, resolve_path=True)],
    out: Annotated[
        Path | None,
        typer.Option(help="Optional output graph JSON path."),
    ] = None,
    min_confidence: Annotated[
        float,
        typer.Option(min=0.0, max=1.0, help="Minimum confidence threshold for graph edges."),
    ] = 0.8,
    top_k_edges: Annotated[
        int,
        typer.Option(
            "--top-k-edges",
            "--graph-top-k-per-pair",
            min=1,
            help="Top K join edges retained per table pair.",
        ),
    ] = 3,
    sample_rows: Annotated[
        int,
        typer.Option(min=1, help="Rows sampled per column for join inference."),
    ] = 10_000,
    sample_seed: Annotated[
        int,
        typer.Option(help="Deterministic seed used for row sampling."),
    ] = 42,
    max_tables: Annotated[
        int | None,
        typer.Option(min=1, help="Maximum files to analyze."),
    ] = None,
    max_columns: Annotated[
        int | None,
        typer.Option(min=1, help="Maximum columns per table to consider."),
    ] = None,
    distinct_low_card_threshold: Annotated[
        int,
        typer.Option(min=1, help="Distinct-count threshold used for low-cardinality trap guard."),
    ] = 64,
    near_unique_threshold: Annotated[
        float,
        typer.Option(
            min=0.0,
            max=1.0,
            help="Near-unique threshold used in profiling, key seeds, and join pruning.",
        ),
    ] = 0.9,
    date_caps: Annotated[
        str | None,
        typer.Option(
            help=(
                "Date caps override as comma-separated key=value pairs, e.g. "
                "'temporal_overlap=0.6,mixed_temporal=0.75'"
            )
        ),
    ] = None,
    join_weight: Annotated[
        list[str] | None,
        typer.Option("--join-weight", help="Override join weight, e.g. jaccard=0.2"),
    ] = None,
    xlsx_sheet: Annotated[
        list[str] | None,
        typer.Option("--xlsx-sheet", help="Per-file sheet mapping, e.g. sales.xlsx=Sheet2"),
    ] = None,
    json_flatten_depth: Annotated[
        int,
        typer.Option(min=0, help="Flatten depth for nested JSON objects."),
    ] = 1,
    fast_profile: Annotated[
        bool,
        typer.Option(help="Enable faster profiling (skips expensive entropy/duplicate scans)."),
    ] = False,
    profile_entropy_cap: Annotated[
        int,
        typer.Option(min=100, help="Max non-null values used for entropy computation per column."),
    ] = 50_000,
) -> None:
    """Build and export join graph as JSON."""
    graph_report = build_graph_report(
        path=path,
        min_confidence=min_confidence,
        sample_rows=sample_rows,
        sample_seed=sample_seed,
        max_tables=max_tables,
        max_columns=max_columns,
        top_k_edges=top_k_edges,
        distinct_low_card_threshold=distinct_low_card_threshold,
        near_unique_threshold=near_unique_threshold,
        date_caps=_parse_float_assignments_csv(date_caps, label="date-caps"),
        fast_profile=fast_profile,
        profile_entropy_cap=profile_entropy_cap,
        join_weights=_parse_weight_assignments(join_weight or []),
        xlsx_sheet_map=_parse_assignments(xlsx_sheet or [], label="xlsx-sheet"),
        json_flatten_depth=json_flatten_depth,
    )
    rendered = graph_report.model_dump_json(indent=2)

    if out is None:
        typer.echo(rendered)
        return

    out.write_text(rendered, encoding="utf-8")
    typer.echo(f"Wrote graph: {out}")


@app.command("export-sql")
def export_sql_command(
    path: Annotated[Path, typer.Argument(..., exists=True, readable=True, resolve_path=True)],
    out: Annotated[
        Path | None,
        typer.Option(help="Optional output SQL file path."),
    ] = None,
    max_tables: Annotated[
        int | None,
        typer.Option(min=1, help="Maximum files to analyze."),
    ] = None,
    max_columns: Annotated[
        int | None,
        typer.Option(min=1, help="Maximum columns per table to consider."),
    ] = None,
    xlsx_sheet: Annotated[
        list[str] | None,
        typer.Option("--xlsx-sheet", help="Per-file sheet mapping, e.g. sales.xlsx=Sheet2"),
    ] = None,
    json_flatten_depth: Annotated[
        int,
        typer.Option(min=0, help="Flatten depth for nested JSON objects."),
    ] = 1,
) -> None:
    """Export SQL DDL skeleton using inferred schema and key candidates."""
    sql = export_sql(
        path=path,
        max_tables=max_tables,
        max_columns=max_columns,
        xlsx_sheet_map=_parse_assignments(xlsx_sheet or [], label="xlsx-sheet"),
        json_flatten_depth=json_flatten_depth,
    )

    if out is None:
        typer.echo(sql)
        return

    out.write_text(sql, encoding="utf-8")
    typer.echo(f"Wrote SQL skeleton: {out}")


@app.command("debug-site")
def debug_site_command(
    path: Annotated[Path, typer.Argument(..., exists=True, readable=True, resolve_path=True)],
    out_dir: Annotated[
        Path,
        typer.Option(help="Output folder for static debug site."),
    ] = Path("perf_outputs") / "debug_site",
    sample_rows: Annotated[
        int,
        typer.Option(min=1, help="Rows sampled per column for join inference."),
    ] = 10_000,
    sample_seed: Annotated[
        int,
        typer.Option(help="Deterministic seed used for row sampling."),
    ] = 42,
    preview_rows: Annotated[
        int,
        typer.Option(min=1, max=200, help="Sample rows per table shown in the viewer."),
    ] = 25,
    max_tables: Annotated[
        int | None,
        typer.Option(min=1, help="Maximum files to analyze."),
    ] = None,
    max_columns: Annotated[
        int | None,
        typer.Option(min=1, help="Maximum columns per table to consider."),
    ] = None,
    min_confidence: Annotated[
        float,
        typer.Option(min=0.0, max=1.0, help="Minimum confidence threshold for relationship lines."),
    ] = 0.75,
    top_k_edges: Annotated[
        int,
        typer.Option(
            "--top-k-edges",
            "--graph-top-k-per-pair",
            min=1,
            help="Top K join edges retained per table pair.",
        ),
    ] = 3,
    distinct_low_card_threshold: Annotated[
        int,
        typer.Option(min=1, help="Distinct-count threshold used for low-cardinality trap guard."),
    ] = 64,
    near_unique_threshold: Annotated[
        float,
        typer.Option(
            min=0.0,
            max=1.0,
            help="Near-unique threshold used in profiling, key seeds, and join pruning.",
        ),
    ] = 0.9,
    date_caps: Annotated[
        str | None,
        typer.Option(
            help=(
                "Date caps override as comma-separated key=value pairs, e.g. "
                "'temporal_overlap=0.6,mixed_temporal=0.75'"
            )
        ),
    ] = None,
    join_weight: Annotated[
        list[str] | None,
        typer.Option("--join-weight", help="Override join weight, e.g. jaccard=0.2"),
    ] = None,
    xlsx_sheet: Annotated[
        list[str] | None,
        typer.Option("--xlsx-sheet", help="Per-file sheet mapping, e.g. sales.xlsx=Sheet2"),
    ] = None,
    json_flatten_depth: Annotated[
        int,
        typer.Option(min=0, help="Flatten depth for nested JSON objects."),
    ] = 1,
    fast_profile: Annotated[
        bool,
        typer.Option(help="Enable faster profiling (skips expensive entropy/duplicate scans)."),
    ] = False,
    profile_entropy_cap: Annotated[
        int,
        typer.Option(min=100, help="Max non-null values used for entropy computation per column."),
    ] = 50_000,
) -> None:
    """Generate a static debug viewer (HTML + JSON) for table relationships and samples."""
    index_path, data_path = build_debug_site(
        path=path,
        out_dir=out_dir,
        sample_rows=sample_rows,
        sample_seed=sample_seed,
        preview_rows=preview_rows,
        max_tables=max_tables,
        max_columns=max_columns,
        min_confidence=min_confidence,
        graph_top_k_per_pair=top_k_edges,
        distinct_low_card_threshold=distinct_low_card_threshold,
        near_unique_threshold=near_unique_threshold,
        date_caps=_parse_float_assignments_csv(date_caps, label="date-caps"),
        fast_profile=fast_profile,
        profile_entropy_cap=profile_entropy_cap,
        join_weights=_parse_weight_assignments(join_weight or []),
        xlsx_sheet_map=_parse_assignments(xlsx_sheet or [], label="xlsx-sheet"),
        json_flatten_depth=json_flatten_depth,
    )
    typer.echo(f"Wrote debug viewer: {index_path}")
    typer.echo(f"Wrote debug data: {data_path}")


def main() -> None:
    """Run Typer app."""
    app()


if __name__ == "__main__":
    main()
