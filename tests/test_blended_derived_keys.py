import csv
import json
import re
import subprocess
import sys
from pathlib import Path


def _contains_derived_pattern(values: list[str]) -> bool:
    pattern = re.compile(r"[a-z]+[-_#/][0-9]+")
    return any(pattern.search(value.strip().lower()) for value in values if value)


def _read_column(path: Path, column: str) -> list[str]:
    values: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            values.append(str(row.get(column, "")))
    return values


def test_retail_blends_one_sided_and_both_sided_derived_keys(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    out_root = tmp_path / "datasets"
    subprocess.run(
        [
            sys.executable,
            "scripts/test_datasets/run.py",
            "--domain",
            "retail",
            "--output-dir",
            str(out_root),
            "--profile",
            "tiny",
            "--seed",
            "17",
            "--pct-derived-keys",
            "0.8",
            "--pct-derived-both-sides",
            "0.7",
        ],
        check=True,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    retail_dir = out_root / "retail"
    manifest = json.loads((retail_dir / "manifest.json").read_text(encoding="utf-8"))
    relationships = manifest["ground_truth"]["core_relationships"]
    assert any(rel.get("derived_side") == "both_tables" for rel in relationships)

    order_customer_keys = _read_column(retail_dir / "orders.csv", "customer_key_id")
    assert _contains_derived_pattern(order_customer_keys)

    payment_ids = _read_column(retail_dir / "payments.csv", "payment_id")
    refund_payment_keys = _read_column(retail_dir / "refunds.csv", "payment_key_id")
    assert _contains_derived_pattern(payment_ids)
    assert _contains_derived_pattern(refund_payment_keys)


def test_health_blends_one_sided_and_both_sided_derived_keys(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    out_root = tmp_path / "datasets"
    subprocess.run(
        [
            sys.executable,
            "scripts/test_datasets/run.py",
            "--domain",
            "health",
            "--output-dir",
            str(out_root),
            "--profile",
            "tiny",
            "--seed",
            "19",
            "--pct-derived-keys",
            "0.8",
            "--pct-derived-both-sides",
            "0.7",
        ],
        check=True,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    health_dir = out_root / "health"
    manifest = json.loads((health_dir / "manifest.json").read_text(encoding="utf-8"))
    relationships = manifest["ground_truth"]["core_relationships"]
    assert any(rel.get("derived_side") == "both_tables" for rel in relationships)

    encounter_patient_keys = _read_column(health_dir / "encounters.csv", "patient_key_id")
    assert _contains_derived_pattern(encounter_patient_keys)

    payment_ids = _read_column(health_dir / "payments.csv", "payment_id")
    adjustment_payment_ids = _read_column(health_dir / "adjustments.csv", "payment_id")
    assert _contains_derived_pattern(payment_ids)
    assert _contains_derived_pattern(adjustment_payment_ids)


def test_saas_blends_one_sided_and_both_sided_derived_keys(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    out_root = tmp_path / "datasets"
    subprocess.run(
        [
            sys.executable,
            "scripts/test_datasets/run.py",
            "--domain",
            "saas",
            "--output-dir",
            str(out_root),
            "--profile",
            "tiny",
            "--seed",
            "23",
            "--pct-derived-keys",
            "0.8",
            "--pct-derived-both-sides",
            "0.7",
        ],
        check=True,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    saas_dir = out_root / "saas"
    manifest = json.loads((saas_dir / "manifest.json").read_text(encoding="utf-8"))
    relationships = manifest["ground_truth"]["core_relationships"]
    assert any(rel.get("derived_side") == "both_tables" for rel in relationships)

    account_keys = _read_column(saas_dir / "users.csv", "account_key_id")
    assert _contains_derived_pattern(account_keys)

    payment_ids = _read_column(saas_dir / "payments.csv", "payment_id")
    refund_payment_ids = _read_column(saas_dir / "refunds.csv", "payment_id")
    assert _contains_derived_pattern(payment_ids)
    assert _contains_derived_pattern(refund_payment_ids)

