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

from test_datasets.common import apply_mixed_table_formats
from test_datasets.domains import derived, health, retail, saas

DOMAIN_ORDER = ("retail", "health", "saas", "derived")
DOMAIN_CHOICES = DOMAIN_ORDER
PROFILE_CHOICES = ("tiny", "small", "medium", "large")


def parse_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description="Generate deterministic Smartjoin test datasets (generation only).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/test_datasets/run.py --output-dir test_datasets\n"
            "  python scripts/test_datasets/run.py --domain retail --profile tiny "
            "--output-dir test_datasets\n"
            "  python scripts/test_datasets/run.py --domain derived --output-dir test_datasets\n"
            "  python scripts/test_datasets/run.py --pct-derived-keys 0.5 "
            "--output-dir test_datasets\n"
            "  python scripts/test_datasets/run.py --domain saas --n-invoices 2000 "
            "--output-dir test_datasets"
        ),
    )

    selection = parser.add_argument_group("Selection")
    selection.add_argument(
        "--domain",
        choices=DOMAIN_CHOICES,
        default=None,
        help="Generate only one domain. If omitted, generate all domains.",
    )
    selection.add_argument(
        "--output-dir",
        type=Path,
        default=Path("test_datasets"),
        help="Root output directory. Domain datasets are written under this root.",
    )
    selection.add_argument("--seed", type=int, default=42, help="Deterministic seed.")
    selection.add_argument(
        "--profile",
        choices=PROFILE_CHOICES,
        default="small",
        help="Size profile forwarded to domain generators.",
    )

    quality = parser.add_argument_group("Data Quality And Key Noise")
    quality.add_argument("--pct-missing", type=float, default=0.02)
    quality.add_argument("--pct-duplicates", type=float, default=0.01)
    quality.add_argument("--pct-dirty-keys", type=float, default=0.04)
    quality.add_argument(
        "--pct-derived-keys",
        type=float,
        default=0.2,
        help="Share of derived-key noise applied on one-sided relationships.",
    )
    quality.add_argument(
        "--pct-derived-both-sides",
        type=float,
        default=0.1,
        help="Share of both-sided derived-key relationships to perturb.",
    )
    quality.add_argument("--pct-inconsistent-types", type=float, default=0.03)

    json_group = parser.add_argument_group("JSON Output")
    json_group.add_argument(
        "--include-json",
        action="store_true",
        help="Generate optional domain-specific nested JSON files.",
    )
    json_group.add_argument(
        "--max-json-records",
        type=int,
        default=None,
        help="Domain-agnostic cap for generated JSON rows (mapped per domain).",
    )

    execution = parser.add_argument_group("Execution")
    execution.add_argument(
        "--clean",
        action="store_true",
        help="Delete domain output folders before generation.",
    )

    return parser.parse_known_args(argv)


def _build_common_args(args: argparse.Namespace) -> list[str]:
    forwarded = [
        "--profile",
        args.profile,
        "--pct-missing",
        str(args.pct_missing),
        "--pct-duplicates",
        str(args.pct_duplicates),
        "--pct-dirty-keys",
        str(args.pct_dirty_keys),
        "--pct-derived-keys",
        str(args.pct_derived_keys),
        "--pct-derived-both-sides",
        str(args.pct_derived_both_sides),
        "--pct-inconsistent-types",
        str(args.pct_inconsistent_types),
    ]
    if args.include_json:
        forwarded.append("--include-json")
    return forwarded


def _run_domain(
    domain: str,
    output_root: Path,
    seed: int,
    common_args: list[str],
    max_json_records: int | None,
    clean: bool,
    passthrough: list[str],
) -> Path:
    domain_out = output_root / domain
    if clean and domain_out.exists():
        shutil.rmtree(domain_out)
    domain_out.parent.mkdir(parents=True, exist_ok=True)

    domain_args = [
        *common_args,
        *passthrough,
        "--out-dir",
        str(domain_out),
        "--seed",
        str(seed),
    ]
    if max_json_records is not None:
        if domain == "retail":
            domain_args.extend(["--max-json-orders", str(max_json_records)])
        elif domain == "health":
            domain_args.extend(["--max-json-encounters", str(max_json_records)])
        elif domain == "saas":
            domain_args.extend(["--max-json-events", str(max_json_records)])

    if domain == "retail":
        retail.main(domain_args)
    elif domain == "health":
        health.main(domain_args)
    elif domain == "saas":
        saas.main(domain_args)
    elif domain == "derived":
        derived.main(domain_args)
    else:
        raise ValueError(f"Unsupported domain: {domain}")

    apply_mixed_table_formats(domain_out)
    return domain_out


def main(argv: list[str] | None = None) -> None:
    args, passthrough = parse_args(argv)
    output_root: Path = args.output_dir
    output_root.mkdir(parents=True, exist_ok=True)

    domains = [args.domain] if args.domain else list(DOMAIN_ORDER)
    if passthrough and not args.domain:
        unknown = " ".join(passthrough)
        raise SystemExit(
            "Unknown/domain-specific options require --domain.\n"
            f"Received: {unknown}\n"
            "Use --help to see explicit common flags in run.py."
        )

    common_args = _build_common_args(args)

    generated = []
    for domain in domains:
        out_dir = _run_domain(
            domain=domain,
            output_root=output_root,
            seed=args.seed,
            common_args=common_args,
            max_json_records=args.max_json_records,
            clean=bool(args.clean),
            passthrough=passthrough,
        )
        generated.append({"domain": domain, "output_dir": str(out_dir)})

    summary = {
        "generator": "scripts/test_datasets/run.py",
        "seed": args.seed,
        "profile": args.profile,
        "pct_missing": args.pct_missing,
        "pct_duplicates": args.pct_duplicates,
        "pct_dirty_keys": args.pct_dirty_keys,
        "pct_derived_keys": args.pct_derived_keys,
        "pct_derived_both_sides": args.pct_derived_both_sides,
        "pct_inconsistent_types": args.pct_inconsistent_types,
        "include_json": bool(args.include_json),
        "max_json_records": args.max_json_records,
        "output_dir": str(output_root),
        "domains": generated,
    }
    summary_path = output_root / "generation_manifest.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote generation manifest: {summary_path}")


if __name__ == "__main__":
    main()
