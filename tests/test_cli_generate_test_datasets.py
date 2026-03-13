import json
import os
import subprocess
import sys
from pathlib import Path


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
    generation_manifest = json.loads(
        (output_root / "generation_manifest.json").read_text(encoding="utf-8")
    )
    generated_domains = [item["domain"] for item in generation_manifest["domains"]]
    assert generated_domains == ["retail"]

