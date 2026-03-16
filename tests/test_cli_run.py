import json
import os
import subprocess
import sys
from pathlib import Path

import polars as pl


def test_cli_run_command_writes_all_outputs(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "artifacts"
    input_dir.mkdir(parents=True, exist_ok=True)

    pl.DataFrame({"customer_id": [1, 2, 3], "name": ["a", "b", "c"]}).write_csv(
        input_dir / "customers.csv"
    )
    pl.DataFrame({"order_id": [10, 11, 12], "customer_id": [1, 2, 2]}).write_csv(
        input_dir / "orders.csv"
    )

    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(repo_root / "src")
        if not existing_pythonpath
        else f"{repo_root / 'src'}{os.pathsep}{existing_pythonpath}"
    )

    subprocess.run(
        [
            sys.executable,
            "-m",
            "smartjoin.cli",
            "run",
            str(input_dir),
            str(output_dir),
            "--sample-rows",
            "500",
            "--preview-rows",
            "5",
        ],
        check=True,
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )

    report_path = output_dir / "report.json"
    relationships_path = output_dir / "relationships.csv"
    viewer_index_path = output_dir / "explorer" / "index.html"
    viewer_data_path = output_dir / "explorer" / "data.json"

    assert report_path.exists()
    assert relationships_path.exists()
    assert viewer_index_path.exists()
    assert viewer_data_path.exists()

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert "joins" in report
    assert "settings" in report

    viewer_payload = json.loads(viewer_data_path.read_text(encoding="utf-8"))
    assert "report" in viewer_payload
    assert "tables" in viewer_payload

    relationships = pl.read_csv(relationships_path)
    assert {"left_table", "left_column", "right_table", "right_column"}.issubset(
        set(relationships.columns)
    )
    assert {"confidence", "relationship_guess", "weighted_score", "is_derived"}.issubset(
        set(relationships.columns)
    )


def test_cli_help_lists_run_and_hides_legacy_commands(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]

    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(repo_root / "src")
        if not existing_pythonpath
        else f"{repo_root / 'src'}{os.pathsep}{existing_pythonpath}"
    )

    result = subprocess.run(
        [sys.executable, "-m", "smartjoin.cli", "--help"],
        check=True,
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )

    assert "run" in result.stdout
    assert "generate-test-datasets" in result.stdout
    assert "analyze" not in result.stdout
    assert "export-sql" not in result.stdout
    assert "debug-site" not in result.stdout


def test_cli_without_command_shows_help(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]

    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(repo_root / "src")
        if not existing_pythonpath
        else f"{repo_root / 'src'}{os.pathsep}{existing_pythonpath}"
    )

    result = subprocess.run(
        [sys.executable, "-m", "smartjoin.cli"],
        check=False,
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Usage: python -m smartjoin.cli [OPTIONS] COMMAND [ARGS]..." in result.stdout
    assert "run" in result.stdout
    assert "Missing command." not in result.stdout


def test_cli_run_without_required_args_shows_run_help(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]

    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(repo_root / "src")
        if not existing_pythonpath
        else f"{repo_root / 'src'}{os.pathsep}{existing_pythonpath}"
    )

    result = subprocess.run(
        [sys.executable, "-m", "smartjoin.cli", "run"],
        check=False,
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Usage: python -m smartjoin.cli run [OPTIONS] PATH OUT_DIR" in result.stdout
    assert "Missing argument 'PATH'." not in result.stdout
