"""CLI entrypoint for Smartjoin."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Annotated, Literal

import typer

from smartjoin.analysis import analyze_path
from smartjoin.explorer import build_explorer

app = typer.Typer(
    help="Deterministic relationship discovery for structured datasets.",
    no_args_is_help=True,
)


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


def _load_test_dataset_runner() -> object:
    """Load scripts/test_datasets/run.py directly to avoid import-path conflicts."""
    repo_root = Path(__file__).resolve().parents[2]
    run_path = repo_root / "scripts" / "test_datasets" / "run.py"
    if not run_path.exists():
        raise typer.BadParameter(
            "Test dataset generators are unavailable: scripts/test_datasets/run.py is missing."
        )
    spec = importlib.util.spec_from_file_location("smartjoin_test_datasets_run", run_path)
    if spec is None or spec.loader is None:
        raise typer.BadParameter(f"Unable to load dataset runner module: {run_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@app.callback()
def root() -> None:
    """Top-level CLI group."""


@app.command("run", no_args_is_help=True)
def run_command(
    path: Annotated[
        Path,
        typer.Argument(
            ...,
            exists=True,
            readable=True,
            resolve_path=True,
            help="Input folder containing data files to analyze.",
        ),
    ],
    out_dir: Annotated[
        Path,
        typer.Argument(..., help="Output folder where all generated artifacts are stored."),
    ],
    format: Annotated[
        str,
        typer.Option(help="Output format for report. Only 'json' is currently supported."),
    ] = "json",
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
    viewer_min_confidence: Annotated[
        float,
        typer.Option(
            min=0.0,
            max=1.0,
            help="Initial confidence threshold for relationship lines in the explorer.",
        ),
    ] = 0.75,
    preview_rows: Annotated[
        int,
        typer.Option(min=1, max=200, help="Sample rows per table shown in the explorer."),
    ] = 25,
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
    """Run Smartjoin workflow and write report plus explorer artifacts."""
    if format.lower() != "json":
        raise typer.BadParameter("Only --format json is supported.")

    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "report.json"
    viewer_dir = out_dir / "explorer"
    parsed_date_caps = _parse_float_assignments_csv(date_caps, label="date-caps")
    parsed_join_weights = _parse_weight_assignments(join_weight or [])
    parsed_xlsx_sheet_map = _parse_assignments(xlsx_sheet or [], label="xlsx-sheet")

    report = analyze_path(
        path=path,
        sample_rows=sample_rows,
        sample_seed=sample_seed,
        max_tables=max_tables,
        max_columns=max_columns,
        min_confidence=min_confidence,
        distinct_low_card_threshold=distinct_low_card_threshold,
        near_unique_threshold=near_unique_threshold,
        date_caps=parsed_date_caps,
        fast_profile=fast_profile,
        profile_entropy_cap=profile_entropy_cap,
        join_weights=parsed_join_weights,
        xlsx_sheet_map=parsed_xlsx_sheet_map,
        json_flatten_depth=json_flatten_depth,
    )
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(f"Wrote report: {report_path}")

    index_path, data_path = build_explorer(
        path=path,
        out_dir=viewer_dir,
        sample_rows=sample_rows,
        sample_seed=sample_seed,
        preview_rows=preview_rows,
        max_tables=max_tables,
        max_columns=max_columns,
        min_confidence=viewer_min_confidence,
        distinct_low_card_threshold=distinct_low_card_threshold,
        near_unique_threshold=near_unique_threshold,
        date_caps=parsed_date_caps,
        fast_profile=fast_profile,
        profile_entropy_cap=profile_entropy_cap,
        join_weights=parsed_join_weights,
        xlsx_sheet_map=parsed_xlsx_sheet_map,
        json_flatten_depth=json_flatten_depth,
        precomputed_report=report,
    )
    typer.echo(f"Wrote explorer UI: {index_path}")
    typer.echo(f"Wrote explorer data: {data_path}")


@app.command(
    "generate-test-datasets",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def generate_test_datasets_command(
    ctx: typer.Context,
    domain: Annotated[
        Literal["retail", "health", "saas", "derived"] | None,
        typer.Option(
            "--domain",
            help="Generate one domain; omit to generate all domains.",
        ),
    ] = None,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Root output directory for generated datasets."),
    ] = Path("test_datasets"),
    seed: Annotated[
        int,
        typer.Option("--seed", help="Deterministic generation seed."),
    ] = 42,
    profile: Annotated[
        Literal["tiny", "small", "medium", "large"],
        typer.Option("--profile", help="Size profile for generated datasets."),
    ] = "small",
    pct_derived_keys: Annotated[
        float,
        typer.Option(
            "--pct-derived-keys",
            min=0.0,
            max=1.0,
            help="Share of one-sided derived-key perturbations.",
        ),
    ] = 0.2,
    pct_derived_both_sides: Annotated[
        float,
        typer.Option(
            "--pct-derived-both-sides",
            min=0.0,
            max=1.0,
            help="Share of both-sided derived-key perturbations.",
        ),
    ] = 0.1,
    pct_missing: Annotated[
        float,
        typer.Option(min=0.0, max=1.0, help="Share of missing values injected."),
    ] = 0.02,
    pct_duplicates: Annotated[
        float,
        typer.Option(min=0.0, max=1.0, help="Share of duplicate rows injected."),
    ] = 0.01,
    pct_dirty_keys: Annotated[
        float,
        typer.Option(min=0.0, max=1.0, help="Share of dirty key formatting noise."),
    ] = 0.04,
    pct_inconsistent_types: Annotated[
        float,
        typer.Option(min=0.0, max=1.0, help="Share of inconsistent type encodings."),
    ] = 0.03,
    include_json: Annotated[
        bool,
        typer.Option("--include-json", help="Generate optional nested JSON files."),
    ] = False,
    max_json_records: Annotated[
        int | None,
        typer.Option(
            "--max-json-records",
            min=1,
            help="Cap for JSON rows generated in each domain.",
        ),
    ] = None,
    clean: Annotated[
        bool,
        typer.Option("--clean", help="Delete target domain output directories first."),
    ] = False,
) -> None:
    """Generate deterministic test datasets."""
    datasets_run = _load_test_dataset_runner()
    argv = [
        "--output-dir",
        str(output_dir),
        "--seed",
        str(seed),
        "--profile",
        profile,
        "--pct-missing",
        str(pct_missing),
        "--pct-duplicates",
        str(pct_duplicates),
        "--pct-dirty-keys",
        str(pct_dirty_keys),
        "--pct-derived-keys",
        str(pct_derived_keys),
        "--pct-derived-both-sides",
        str(pct_derived_both_sides),
        "--pct-inconsistent-types",
        str(pct_inconsistent_types),
    ]
    if include_json:
        argv.append("--include-json")
    if max_json_records is not None:
        argv.extend(["--max-json-records", str(max_json_records)])
    if domain:
        argv.extend(["--domain", domain])
    if clean:
        argv.append("--clean")
    argv.extend(ctx.args)
    datasets_run.main(argv)


def main() -> None:
    """Run Typer app."""
    app()


if __name__ == "__main__":
    main()
