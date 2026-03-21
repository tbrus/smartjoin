import json
import re
import subprocess
import sys
from pathlib import Path

from smartjoin.ingestion import load_tables


def _contains_derived_pattern(values: list[str]) -> bool:
    pattern = re.compile(r"[a-z]+[-_#/][0-9]+")
    return any(pattern.search(value.strip().lower()) for value in values if value)


def _run_checked(command: list[str], *, cwd: Path) -> None:
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Command failed: {' '.join(command)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


def _read_table_column(dataset_dir: Path, table_name: str, column: str) -> list[str]:
    tables = load_tables(dataset_dir)
    by_name = {table.name: table for table in tables}
    if table_name not in by_name:
        raise AssertionError(f"Missing expected table: {table_name}")
    if column not in by_name[table_name].df.columns:
        raise AssertionError(f"Missing expected column: {table_name}.{column}")
    return [str(value) for value in by_name[table_name].df[column].to_list()]


def test_retail_blends_one_sided_and_both_sided_derived_keys(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    out_root = tmp_path / "datasets"
    _run_checked(
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
        cwd=repo_root,
    )

    retail_dir = out_root / "retail"
    manifest = json.loads((retail_dir / "manifest.json").read_text(encoding="utf-8"))
    relationships = manifest["ground_truth"]["core_relationships"]
    assert any(rel.get("derived_side") == "both_tables" for rel in relationships)

    order_customer_keys = _read_table_column(retail_dir, "orders", "customer_key_id")
    assert _contains_derived_pattern(order_customer_keys)

    payment_ids = _read_table_column(retail_dir, "payments", "payment_id")
    refund_payment_keys = _read_table_column(retail_dir, "refunds", "payment_key_id")
    assert _contains_derived_pattern(payment_ids)
    assert _contains_derived_pattern(refund_payment_keys)


def test_health_blends_one_sided_and_both_sided_derived_keys(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    out_root = tmp_path / "datasets"
    _run_checked(
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
        cwd=repo_root,
    )

    health_dir = out_root / "health"
    manifest = json.loads((health_dir / "manifest.json").read_text(encoding="utf-8"))
    relationships = manifest["ground_truth"]["core_relationships"]
    assert any(rel.get("derived_side") == "both_tables" for rel in relationships)

    encounter_patient_keys = _read_table_column(health_dir, "encounters", "patient_key_id")
    assert _contains_derived_pattern(encounter_patient_keys)

    payment_ids = _read_table_column(health_dir, "payments", "payment_id")
    adjustment_payment_ids = _read_table_column(health_dir, "adjustments", "payment_id")
    assert _contains_derived_pattern(payment_ids)
    assert _contains_derived_pattern(adjustment_payment_ids)


def test_saas_blends_one_sided_and_both_sided_derived_keys(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    out_root = tmp_path / "datasets"
    _run_checked(
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
        cwd=repo_root,
    )

    saas_dir = out_root / "saas"
    manifest = json.loads((saas_dir / "manifest.json").read_text(encoding="utf-8"))
    relationships = manifest["ground_truth"]["core_relationships"]
    assert any(rel.get("derived_side") == "both_tables" for rel in relationships)

    account_keys = _read_table_column(saas_dir, "users", "account_key_id")
    assert _contains_derived_pattern(account_keys)

    payment_ids = _read_table_column(saas_dir, "payments", "payment_id")
    refund_payment_ids = _read_table_column(saas_dir, "refunds", "payment_id")
    assert _contains_derived_pattern(payment_ids)
    assert _contains_derived_pattern(refund_payment_ids)
