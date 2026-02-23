import json
import subprocess
import sys
from pathlib import Path

from smartjoin.analysis import analyze_path


def test_health_generator_writes_ground_truth_and_traps(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    out_dir = tmp_path / "health_dataset"

    subprocess.run(
        [
            sys.executable,
            "scripts/generate_smartjoin_health_testdata.py",
            "--out-dir",
            str(out_dir),
            "--seed",
            "17",
            "--n-patients",
            "80",
            "--n-providers",
            "20",
            "--n-facilities",
            "10",
            "--n-payers",
            "8",
            "--n-encounters",
            "160",
            "--n-claims",
            "140",
            "--avg-claim-lines",
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
        rel["from_table"] == "claims"
        and rel["from_column"] == "encounter_id"
        and rel["to_table"] == "encounters"
        and rel["to_column"] == "encounter_id"
        for rel in core_relationships
    )
    assert any(
        rel["from_table"] == "adjustments"
        and rel["from_column"] == "payment_id"
        and rel["to_table"] == "payments"
        and rel["to_column"] == "payment_id"
        for rel in core_relationships
    )
    assert any(
        trap["columns"] == ["facilities.region_code", "payers.region_code"]
        for trap in traps["overlapping_value_traps"]
    )
    assert "status" in traps["shared_low_cardinality_columns"]
    assert manifest["expected_joins"]


def test_health_generator_core_join_recall(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    out_dir = tmp_path / "health_dataset"

    subprocess.run(
        [
            sys.executable,
            "scripts/generate_smartjoin_health_testdata.py",
            "--out-dir",
            str(out_dir),
            "--seed",
            "19",
            "--n-patients",
            "120",
            "--n-providers",
            "30",
            "--n-facilities",
            "12",
            "--n-payers",
            "10",
            "--n-encounters",
            "260",
            "--n-claims",
            "230",
            "--avg-claim-lines",
            "2.1",
        ],
        check=True,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    report = analyze_path(path=out_dir, sample_rows=3_000, min_confidence=0.68)

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
