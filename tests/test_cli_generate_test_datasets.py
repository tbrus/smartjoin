import json
import os
import subprocess
import sys
from pathlib import Path

EXPECTED_TABLE_FORMATS = {".csv", ".json", ".parquet", ".xlsx"}


def _emitted_table_formats(domain_dir: Path) -> set[str]:
    files = [
        path
        for path in domain_dir.iterdir()
        if path.is_file()
        and path.suffix.lower() in EXPECTED_TABLE_FORMATS
        and path.name != "manifest.json"
    ]
    return {path.suffix.lower() for path in files}


def test_cli_generate_test_datasets_command(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    output_root = tmp_path / "datasets"

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
            "generate-test-datasets",
            "--domain",
            "retail",
            "--output-dir",
            str(output_root),
            "--seed",
            "7",
            "--profile",
            "tiny",
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
        env=env,
        capture_output=True,
        text=True,
    )

    retail_dir = output_root / "retail"
    assert (retail_dir / "manifest.json").exists()
    assert EXPECTED_TABLE_FORMATS.issubset(_emitted_table_formats(retail_dir))
    generation_manifest = json.loads(
        (output_root / "generation_manifest.json").read_text(encoding="utf-8")
    )
    generated_domains = [item["domain"] for item in generation_manifest["domains"]]
    assert generated_domains == ["retail"]


def test_cli_generate_test_datasets_all_domains_with_derived_flags(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    output_root = tmp_path / "datasets"

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
            "generate-test-datasets",
            "--output-dir",
            str(output_root),
            "--seed",
            "13",
            "--profile",
            "tiny",
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
        env=env,
        capture_output=True,
        text=True,
    )

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

    for domain in generated_domains:
        manifest = json.loads((output_root / domain / "manifest.json").read_text(encoding="utf-8"))
        assert EXPECTED_TABLE_FORMATS.issubset(_emitted_table_formats(output_root / domain))
        assert manifest["config"]["pct_missing"] == 0.03
        assert manifest["config"]["pct_duplicates"] == 0.02
        assert manifest["config"]["pct_dirty_keys"] == 0.07
        assert manifest["config"]["pct_derived_keys"] == 0.5
        assert manifest["config"]["pct_derived_both_sides"] == 0.25
        assert manifest["config"]["pct_inconsistent_types"] == 0.05
        assert manifest["config"]["include_json"] is True


def test_cli_generate_test_datasets_derived_domain(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    output_root = tmp_path / "datasets"

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
            "generate-test-datasets",
            "--domain",
            "derived",
            "--output-dir",
            str(output_root),
            "--seed",
            "17",
            "--profile",
            "tiny",
        ],
        check=True,
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )

    derived_dir = output_root / "derived"
    assert (derived_dir / "manifest.json").exists()
    assert EXPECTED_TABLE_FORMATS.issubset(_emitted_table_formats(derived_dir))
    generation_manifest = json.loads(
        (output_root / "generation_manifest.json").read_text(encoding="utf-8")
    )
    generated_domains = [item["domain"] for item in generation_manifest["domains"]]
    assert generated_domains == ["derived"]
