import json
import subprocess
import sys
from csv import DictReader
from pathlib import Path

from alchemia.analysis import analyze_path


def test_generator_writes_core_relationship_and_trap_summary(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    out_dir = tmp_path / "generated_dataset"

    subprocess.run(
        [
            sys.executable,
            "scripts/generate_alchemia_testdata.py",
            "--out-dir",
            str(out_dir),
            "--seed",
            "7",
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

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    ground_truth = manifest["ground_truth"]
    core_relationships = ground_truth["core_relationships"]
    traps = ground_truth["traps"]

    assert any(
        relationship["from_table"] == "orders"
        and relationship["from_column"] == "customer_key_id"
        and relationship["to_table"] == "customers"
        and relationship["to_column"] == "customer_id"
        for relationship in core_relationships
    )
    assert any(
        relationship["from_table"] == "order_items"
        and relationship["from_column"] == "product_id"
        and relationship["to_table"] == "products"
        for relationship in core_relationships
    )
    assert any(
        trap["columns"] == ["customers.region_code", "products.region_code"]
        for trap in traps["overlapping_value_traps"]
    )
    assert "country" in traps["shared_low_cardinality_columns"]
    assert any(
        pair["left"] == "customers.cust_id" and pair["right"] == "orders.customer_key_id"
        for pair in traps["misleading_name_pairs"]
    )
    assert manifest["expected_joins"]

    customers_regions: set[str] = set()
    with (out_dir / "customers.csv").open("r", encoding="utf-8") as handle:
        reader = DictReader(handle)
        for row in reader:
            customers_regions.add(row["region_code"])

    products_regions: set[str] = set()
    with (out_dir / "products.csv").open("r", encoding="utf-8") as handle:
        reader = DictReader(handle)
        for row in reader:
            products_regions.add(row["region_code"])

    assert len(customers_regions & products_regions) > 0

    readme = (out_dir / "README.md").read_text(encoding="utf-8")
    assert "## Core True Relationships" in readme
    assert "## Trap Signals (Should Not Be Primary Join Keys)" in readme
    assert "region_code" in readme


def test_analyze_recovers_core_ground_truth_joins_on_dirty_generated_data(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    out_dir = tmp_path / "generated_dataset"

    subprocess.run(
        [
            sys.executable,
            "scripts/generate_alchemia_testdata.py",
            "--out-dir",
            str(out_dir),
            "--seed",
            "11",
            "--n-customers",
            "80",
            "--n-products",
            "40",
            "--n-orders",
            "150",
            "--avg-items-per-order",
            "2.2",
        ],
        check=True,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    report = analyze_path(path=out_dir, sample_rows=5_000, min_confidence=0.65)

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
    assert recall >= 0.9
