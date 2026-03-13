import json
import subprocess
import sys
from pathlib import Path

from smartjoin.analysis import analyze_path


def test_saas_generator_writes_ground_truth_and_traps(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    output_root = tmp_path
    out_dir = output_root / "saas"

    subprocess.run(
        [
            sys.executable,
            "scripts/test_datasets/run.py",
            "--domain",
            "saas",
            "--output-dir",
            str(output_root),
            "--seed",
            "23",
            "--n-accounts",
            "120",
            "--n-users",
            "350",
            "--n-workspaces",
            "180",
            "--n-plans",
            "12",
            "--n-features",
            "30",
            "--n-subscriptions",
            "160",
            "--n-invoices",
            "500",
            "--n-usage-events",
            "900",
            "--avg-invoice-lines",
            "2.0",
            "--include-json",
        ],
        check=True,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    core_relationships = manifest["ground_truth"]["core_relationships"]
    traps = manifest["ground_truth"]["traps"]

    assert any(
        rel["from_table"] == "invoices"
        and rel["from_column"] == "subscription_id"
        and rel["to_table"] == "subscriptions"
        and rel["to_column"] == "subscription_id"
        for rel in core_relationships
    )
    assert any(
        rel["from_table"] == "payments"
        and rel["from_column"] == "invoice_id"
        and rel["to_table"] == "invoices"
        and rel["to_column"] == "invoice_id"
        for rel in core_relationships
    )
    assert any(
        trap["columns"] == ["accounts.region_code", "plans.region_code"]
        for trap in traps["overlapping_value_traps"]
    )
    assert "status" in traps["shared_low_cardinality_columns"]
    assert manifest["expected_joins"]


def test_saas_generator_core_join_recall(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    output_root = tmp_path
    out_dir = output_root / "saas"

    subprocess.run(
        [
            sys.executable,
            "scripts/test_datasets/run.py",
            "--domain",
            "saas",
            "--output-dir",
            str(output_root),
            "--seed",
            "29",
            "--n-accounts",
            "150",
            "--n-users",
            "500",
            "--n-workspaces",
            "220",
            "--n-plans",
            "14",
            "--n-features",
            "36",
            "--n-subscriptions",
            "180",
            "--n-invoices",
            "700",
            "--n-usage-events",
            "1300",
            "--avg-invoice-lines",
            "2.3",
        ],
        check=True,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    report = analyze_path(path=out_dir, sample_rows=4_000, min_confidence=0.68)

    def normalize_edge(
        left_table: str,
        left_column: str,
        right_table: str,
        right_column: str,
    ) -> tuple[str, str]:
        endpoints = [f"{left_table}.{left_column}", f"{right_table}.{right_column}"]
        endpoints.sort()
        return endpoints[0], endpoints[1]

    expected = {
        normalize_edge(
            relationship["from_table"],
            relationship["from_column"],
            relationship["to_table"],
            relationship["to_column"],
        )
        for relationship in manifest["ground_truth"]["core_relationships"]
    }
    predicted = {
        normalize_edge(
            join.left_table,
            join.left_column,
            join.right_table,
            join.right_column,
        )
        for join in report.joins
    }

    matched = expected & predicted
    recall = 0.0 if not expected else len(matched) / len(expected)
    assert recall >= 0.8
