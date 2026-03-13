"""Unified CLI for generation-only Smartjoin test datasets."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

if __package__ in {None, ""}:
    # Allow `python scripts/test_datasets/run.py` to import `test_datasets.*`.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_datasets.domains import health, retail, saas

DOMAIN_ORDER = ("retail", "health", "saas")


def parse_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description="Generate deterministic Smartjoin test datasets by domain."
    )
    parser.add_argument(
        "--domain",
        choices=DOMAIN_ORDER,
        default=None,
        help="Generate only one domain. If omitted, generate all domains.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("test_datasets"),
        help="Root output directory. Domain datasets are written under this root.",
    )
    parser.add_argument("--seed", type=int, default=42, help="Deterministic seed.")
    parser.add_argument(
        "--profile",
        choices=["tiny", "small", "medium", "large"],
        default="small",
        help="Size profile forwarded to domain generators.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete domain output folders before generation.",
    )
    return parser.parse_known_args(argv)


def _run_domain(
    domain: str,
    output_root: Path,
    seed: int,
    clean: bool,
    passthrough: list[str],
) -> Path:
    domain_out = output_root / domain
    if clean and domain_out.exists():
        shutil.rmtree(domain_out)
    domain_out.parent.mkdir(parents=True, exist_ok=True)

    if domain == "retail":
        retail.main([*passthrough, "--out-dir", str(domain_out), "--seed", str(seed)])
    elif domain == "health":
        health.main([*passthrough, "--out-dir", str(domain_out), "--seed", str(seed)])
    elif domain == "saas":
        saas.main([*passthrough, "--out-dir", str(domain_out), "--seed", str(seed)])
    else:
        raise ValueError(f"Unsupported domain: {domain}")

    return domain_out


def main(argv: list[str] | None = None) -> None:
    args, passthrough = parse_args(argv)
    output_root: Path = args.output_dir
    output_root.mkdir(parents=True, exist_ok=True)

    domains = [args.domain] if args.domain else list(DOMAIN_ORDER)
    if passthrough and not args.domain:
        raise SystemExit("Domain-specific flags require --domain.")
    forwarded_passthrough = [*passthrough, "--profile", args.profile]

    generated = []
    for domain in domains:
        out_dir = _run_domain(
            domain=domain,
            output_root=output_root,
            seed=args.seed,
            clean=bool(args.clean),
            passthrough=forwarded_passthrough,
        )
        generated.append({"domain": domain, "output_dir": str(out_dir)})

    summary = {
        "generator": "scripts/test_datasets/run.py",
        "seed": args.seed,
        "output_dir": str(output_root),
        "domains": generated,
    }
    summary_path = output_root / "generation_manifest.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote generation manifest: {summary_path}")


if __name__ == "__main__":
    main()
