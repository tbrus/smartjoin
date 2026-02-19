"""Generate and evaluate a multi-scenario performance/generalization suite."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from alchemia.analysis import analyze_path
from alchemia.debug_site import build_debug_site


@dataclass(frozen=True)
class Scenario:
    """One dataset generation/evaluation scenario."""

    name: str
    profile: str
    seed: int
    pct_missing: float
    pct_duplicates: float
    pct_dirty_keys: float
    pct_inconsistent_types: float
    include_json: bool
    min_confidence: float
    sample_rows: int
    generator_script: str = "scripts/generate_alchemia_testdata.py"


DEFAULT_SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        name="baseline_small",
        profile="small",
        seed=42,
        pct_missing=0.02,
        pct_duplicates=0.01,
        pct_dirty_keys=0.04,
        pct_inconsistent_types=0.03,
        include_json=False,
        min_confidence=0.8,
        sample_rows=10_000,
    ),
    Scenario(
        name="dirty_small",
        profile="small",
        seed=314,
        pct_missing=0.03,
        pct_duplicates=0.02,
        pct_dirty_keys=0.12,
        pct_inconsistent_types=0.08,
        include_json=False,
        min_confidence=0.75,
        sample_rows=12_000,
    ),
    Scenario(
        name="sparse_small",
        profile="small",
        seed=2718,
        pct_missing=0.10,
        pct_duplicates=0.01,
        pct_dirty_keys=0.05,
        pct_inconsistent_types=0.05,
        include_json=False,
        min_confidence=0.72,
        sample_rows=12_000,
    ),
    Scenario(
        name="mixed_json_small",
        profile="small",
        seed=1618,
        pct_missing=0.03,
        pct_duplicates=0.01,
        pct_dirty_keys=0.07,
        pct_inconsistent_types=0.05,
        include_json=True,
        min_confidence=0.72,
        sample_rows=12_000,
    ),
    Scenario(
        name="baseline_medium",
        profile="medium",
        seed=99,
        pct_missing=0.02,
        pct_duplicates=0.01,
        pct_dirty_keys=0.04,
        pct_inconsistent_types=0.03,
        include_json=False,
        min_confidence=0.8,
        sample_rows=15_000,
    ),
    Scenario(
        name="health_baseline_small",
        profile="small",
        seed=2026,
        pct_missing=0.02,
        pct_duplicates=0.01,
        pct_dirty_keys=0.04,
        pct_inconsistent_types=0.03,
        include_json=False,
        min_confidence=0.8,
        sample_rows=10_000,
        generator_script="scripts/generate_alchemia_health_testdata.py",
    ),
    Scenario(
        name="health_dirty_small",
        profile="small",
        seed=2027,
        pct_missing=0.04,
        pct_duplicates=0.02,
        pct_dirty_keys=0.11,
        pct_inconsistent_types=0.08,
        include_json=True,
        min_confidence=0.75,
        sample_rows=12_000,
        generator_script="scripts/generate_alchemia_health_testdata.py",
    ),
    Scenario(
        name="saas_baseline_small",
        profile="small",
        seed=3030,
        pct_missing=0.02,
        pct_duplicates=0.01,
        pct_dirty_keys=0.04,
        pct_inconsistent_types=0.03,
        include_json=False,
        min_confidence=0.8,
        sample_rows=10_000,
        generator_script="scripts/generate_alchemia_saas_testdata.py",
    ),
    Scenario(
        name="saas_dirty_small",
        profile="small",
        seed=3031,
        pct_missing=0.04,
        pct_duplicates=0.02,
        pct_dirty_keys=0.10,
        pct_inconsistent_types=0.08,
        include_json=True,
        min_confidence=0.74,
        sample_rows=12_000,
        generator_script="scripts/generate_alchemia_saas_testdata.py",
    ),
)


def _edge_key(left: str, right: str) -> tuple[str, str]:
    endpoints = sorted([left, right])
    return endpoints[0], endpoints[1]


def _expected_edges(manifest: dict[str, object]) -> set[tuple[str, str]]:
    ground_truth = manifest.get("ground_truth", {})
    core = ground_truth.get("core_relationships", []) if isinstance(ground_truth, dict) else []
    expected: set[tuple[str, str]] = set()
    for relationship in core:
        if not isinstance(relationship, dict):
            continue
        from_table = relationship.get("from_table")
        from_column = relationship.get("from_column")
        to_table = relationship.get("to_table")
        to_column = relationship.get("to_column")
        if not all(
            isinstance(item, str)
            for item in [from_table, from_column, to_table, to_column]
        ):
            continue
        expected.add(_edge_key(f"{from_table}.{from_column}", f"{to_table}.{to_column}"))
    return expected


def _predicted_edges(report_joins: list[object], threshold: float) -> set[tuple[str, str]]:
    predicted: set[tuple[str, str]] = set()
    for join in report_joins:
        if not isinstance(join, dict):
            continue
        confidence = float(join.get("confidence", 0.0))
        if confidence < threshold:
            continue
        left_table = join.get("left_table")
        left_column = join.get("left_column")
        right_table = join.get("right_table")
        right_column = join.get("right_column")
        if not all(
            isinstance(item, str)
            for item in [left_table, left_column, right_table, right_column]
        ):
            continue
        predicted.add(
            _edge_key(
                f"{left_table}.{left_column}",
                f"{right_table}.{right_column}",
            )
        )
    return predicted


def _run_generation(repo_root: Path, out_dir: Path, scenario: Scenario) -> float:
    started = time.perf_counter()
    command = [
        sys.executable,
        scenario.generator_script,
        "--out-dir",
        str(out_dir),
        "--profile",
        scenario.profile,
        "--seed",
        str(scenario.seed),
        "--pct-missing",
        str(scenario.pct_missing),
        "--pct-duplicates",
        str(scenario.pct_duplicates),
        "--pct-dirty-keys",
        str(scenario.pct_dirty_keys),
        "--pct-inconsistent-types",
        str(scenario.pct_inconsistent_types),
    ]
    if scenario.include_json:
        command.append("--include-json")
    subprocess.run(command, cwd=repo_root, check=True, capture_output=True, text=True)
    return time.perf_counter() - started


def _run_analysis(
    dataset_dir: Path,
    output_dir: Path,
    scenario: Scenario,
) -> tuple[dict[str, object], dict[str, float], dict[str, str]]:
    started = time.perf_counter()
    report = analyze_path(
        path=dataset_dir,
        sample_rows=scenario.sample_rows,
        sample_seed=scenario.seed,
        min_confidence=scenario.min_confidence,
        graph_top_k_per_pair=3,
    )
    analysis_elapsed = time.perf_counter() - started

    output_dir.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json")
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    debug_started = time.perf_counter()
    debug_index_path, debug_data_path = build_debug_site(
        path=dataset_dir,
        out_dir=output_dir / "html",
        sample_rows=scenario.sample_rows,
        sample_seed=scenario.seed,
        min_confidence=scenario.min_confidence,
        graph_top_k_per_pair=3,
        precomputed_report=report,
    )
    debug_elapsed = time.perf_counter() - debug_started

    return payload, {"analysis": analysis_elapsed, "debug_site": debug_elapsed}, {
        "report": str(report_path),
        "debug_index": str(debug_index_path),
        "debug_data": str(debug_data_path),
    }


def _evaluate(
    manifest: dict[str, object],
    report_payload: dict[str, object],
    threshold: float,
) -> dict[str, object]:
    expected = _expected_edges(manifest)
    predicted = _predicted_edges(report_payload.get("joins", []), threshold=threshold)
    matched = expected & predicted
    missing = expected - predicted
    unexpected = predicted - expected

    precision = 0.0 if not predicted else len(matched) / len(predicted)
    recall = 0.0 if not expected else len(matched) / len(expected)
    f1 = 0.0 if (precision + recall) == 0 else 2 * precision * recall / (precision + recall)

    return {
        "counts": {
            "expected": len(expected),
            "predicted": len(predicted),
            "matched": len(matched),
            "missing": len(missing),
            "unexpected": len(unexpected),
        },
        "metrics": {
            "precision": precision,
            "recall": recall,
            "f1": f1,
        },
        "missing_edges": [f"{a} <-> {b}" for a, b in sorted(missing)],
        "unexpected_edges": [f"{a} <-> {b}" for a, b in sorted(unexpected)],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate and evaluate multi-scenario Alchemia perf suite."
    )
    parser.add_argument(
        "--datasets-root",
        "--out-root",
        dest="datasets_root",
        type=Path,
        default=Path("perf_data") / "datasets",
        help="Root folder for generated scenario dataset folders.",
    )
    parser.add_argument(
        "--outputs-root",
        type=Path,
        default=Path("perf_outputs"),
        help="Root folder for analysis outputs (report.json + html) and suite summary.",
    )
    parser.add_argument(
        "--skip-analysis",
        action="store_true",
        help="Only generate datasets; do not run Alchemia analysis/evaluation.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    datasets_root: Path = args.datasets_root
    outputs_root: Path = args.outputs_root
    datasets_root.mkdir(parents=True, exist_ok=True)
    outputs_root.mkdir(parents=True, exist_ok=True)

    summary: dict[str, object] = {
        "generator": "scripts/generate_perf_suite.py",
        "datasets_root": str(datasets_root),
        "outputs_root": str(outputs_root),
        "scenarios": [],
    }

    for scenario in DEFAULT_SCENARIOS:
        scenario_dir = datasets_root / scenario.name
        scenario_output_dir = outputs_root / scenario.name
        generation_seconds = _run_generation(
            repo_root=repo_root,
            out_dir=scenario_dir,
            scenario=scenario,
        )
        scenario_result: dict[str, object] = {
            "name": scenario.name,
            "config": {
                "profile": scenario.profile,
                "seed": scenario.seed,
                "pct_missing": scenario.pct_missing,
                "pct_duplicates": scenario.pct_duplicates,
                "pct_dirty_keys": scenario.pct_dirty_keys,
                "pct_inconsistent_types": scenario.pct_inconsistent_types,
                "include_json": scenario.include_json,
                "min_confidence": scenario.min_confidence,
                "sample_rows": scenario.sample_rows,
                "generator_script": scenario.generator_script,
            },
            "timing_seconds": {"generation": generation_seconds},
            "dataset_path": str(scenario_dir),
            "outputs_path": str(scenario_output_dir),
        }

        if not args.skip_analysis:
            manifest = json.loads((scenario_dir / "manifest.json").read_text(encoding="utf-8"))
            report_payload, analysis_timings, output_files = _run_analysis(
                dataset_dir=scenario_dir,
                output_dir=scenario_output_dir,
                scenario=scenario,
            )
            scenario_result["timing_seconds"].update(analysis_timings)
            scenario_result["output_files"] = output_files
            scenario_result["evaluation"] = _evaluate(
                manifest=manifest,
                report_payload=report_payload,
                threshold=scenario.min_confidence,
            )

        summary["scenarios"].append(scenario_result)
        print(
            "Scenario ready: "
            f"{scenario.name} -> dataset={scenario_dir} outputs={scenario_output_dir}"
        )

    summary_path = outputs_root / "suite_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote suite summary: {summary_path}")


if __name__ == "__main__":
    main()
