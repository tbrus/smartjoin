import json
import subprocess
import sys
from pathlib import Path


def test_run_cli_single_domain_with_passthrough_args(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    output_root = tmp_path / "datasets"

    subprocess.run(
        [
            sys.executable,
            "scripts/test_datasets/run.py",
            "--domain",
            "retail",
            "--seed",
            "7",
            "--output-dir",
            str(output_root),
            "--n-customers",
            "60",
            "--n-products",
            "30",
            "--n-orders",
            "120",
            "--avg-items-per-order",
            "2.0",
        ],
        check=True,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    retail_dir = output_root / "retail"
    assert (retail_dir / "manifest.json").exists()

    manifest = json.loads((retail_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["row_counts"]["customers"] > 0
    assert manifest["ground_truth"]["core_relationships"]


def test_run_cli_all_domains_with_tiny_profile(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    output_root = tmp_path / "datasets"

    subprocess.run(
        [
            sys.executable,
            "scripts/test_datasets/run.py",
            "--output-dir",
            str(output_root),
            "--profile",
            "tiny",
            "--seed",
            "11",
            "--pct-missing",
            "0.03",
            "--pct-duplicates",
            "0.02",
            "--pct-dirty-keys",
            "0.07",
            "--pct-derived-keys",
            "0.5",
            "--pct-derived-both-sides",
            "0.25",
            "--pct-inconsistent-types",
            "0.05",
            "--include-json",
            "--max-json-records",
            "123",
        ],
        check=True,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    assert (output_root / "retail" / "manifest.json").exists()
    assert (output_root / "health" / "manifest.json").exists()
    assert (output_root / "saas" / "manifest.json").exists()
    assert (output_root / "derived" / "manifest.json").exists()

    generation_manifest = json.loads(
        (output_root / "generation_manifest.json").read_text(encoding="utf-8")
    )
    generated_domains = [item["domain"] for item in generation_manifest["domains"]]
    assert generated_domains == ["retail", "health", "saas", "derived"]
    assert generation_manifest["pct_missing"] == 0.03
    assert generation_manifest["pct_duplicates"] == 0.02
    assert generation_manifest["pct_dirty_keys"] == 0.07
    assert generation_manifest["pct_derived_keys"] == 0.5
    assert generation_manifest["pct_derived_both_sides"] == 0.25
    assert generation_manifest["pct_inconsistent_types"] == 0.05
    assert generation_manifest["include_json"] is True
    assert generation_manifest["max_json_records"] == 123

    for domain in ["retail", "health", "saas", "derived"]:
        manifest = json.loads((output_root / domain / "manifest.json").read_text(encoding="utf-8"))
        assert {
            "generator",
            "config",
            "row_counts",
            "expected_joins",
            "trap_columns",
            "ground_truth",
        }.issubset(manifest.keys())
        assert {
            "core_tables",
            "core_relationships",
            "composite_key_candidates",
            "traps",
            "guard_expectations",
            "regression_cases",
        }.issubset(manifest["ground_truth"].keys())
        assert manifest["config"]["pct_missing"] == 0.03
        assert manifest["config"]["pct_duplicates"] == 0.02
        assert manifest["config"]["pct_dirty_keys"] == 0.07
        assert manifest["config"]["pct_derived_keys"] == 0.5
        assert manifest["config"]["pct_derived_both_sides"] == 0.25
        assert manifest["config"]["pct_inconsistent_types"] == 0.05
        assert manifest["config"]["include_json"] is True


def test_run_cli_derived_domain(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    output_root = tmp_path / "datasets"

    subprocess.run(
        [
            sys.executable,
            "scripts/test_datasets/run.py",
            "--domain",
            "derived",
            "--output-dir",
            str(output_root),
            "--profile",
            "tiny",
            "--seed",
            "5",
        ],
        check=True,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    derived_dir = output_root / "derived"
    assert (derived_dir / "manifest.json").exists()

    manifest = json.loads((derived_dir / "manifest.json").read_text(encoding="utf-8"))
    case_names = {item["name"] for item in manifest["ground_truth"]["regression_cases"]}
    assert {
        "prefix_swap",
        "strip_non_alnum",
        "remove_prefix_numeric",
        "ambiguous_collision_guard",
        "date_like_guard",
        "wide_budget_stress",
    }.issubset(case_names)
