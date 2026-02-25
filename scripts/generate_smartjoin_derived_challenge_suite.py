"""Generate deterministic challenge datasets focused on derived-key joins."""

from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Profile:
    name: str
    n_entities: int
    n_events: int


PROFILES: dict[str, Profile] = {
    "tiny": Profile(name="tiny", n_entities=1_000, n_events=4_000),
    "small": Profile(name="small", n_entities=8_000, n_events=36_000),
    "medium": Profile(name="medium", n_entities=25_000, n_events=140_000),
}


@dataclass(frozen=True)
class Config:
    out_root: Path
    profile: str
    seed: int
    clean: bool


def _id(prefix: str, value: int, width: int = 7) -> str:
    return f"{prefix}{value:0{width}d}"


def _num(value: int, width: int = 8) -> str:
    return f"{value:0{width}d}"


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> int:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def _write_scenario_files(
    scenario_dir: Path,
    manifest: dict[str, Any],
    row_counts: dict[str, int],
) -> None:
    manifest["row_counts"] = row_counts
    (scenario_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    lines = [
        f"# {manifest['scenario_name']}",
        "",
        manifest["description"],
        "",
        "## Challenge Columns",
    ]
    for item in manifest.get("challenge_columns", []):
        lines.append(f"- {item}")
    lines.extend(["", "## Ground Truth", "Core relationships expected to be recoverable:"])
    for rel in manifest.get("ground_truth", {}).get("core_relationships", []):
        lines.append(
            f"- {rel['from_table']}.{rel['from_column']} -> "
            f"{rel['to_table']}.{rel['to_column']} ({rel.get('join_type', 'join')})"
        )
    rejects = manifest.get("ground_truth", {}).get("expected_rejections", [])
    if rejects:
        lines.extend(["", "Expected rejections (false positives to avoid):"])
        for rel in rejects:
            lines.append(
                f"- {rel['from_table']}.{rel['from_column']} x "
                f"{rel['to_table']}.{rel['to_column']}: {rel.get('reason', '')}".rstrip(": ")
            )
    (scenario_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _scenario_prefix_swap_namespace(
    out_dir: Path,
    profile: Profile,
    rng: random.Random,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    n = profile.n_entities
    m = profile.n_events

    products = [
        {
            "product_id": _id("prd", i),
            "product_name": f"product_{i}",
            "region_code": f"R{((i % 40) + 1):02d}",
        }
        for i in range(1, n + 1)
    ]
    customers = [
        {
            "customer_id": f"cust-{i:07d}",
            "segment": rng.choice(["free", "pro", "enterprise"]),
        }
        for i in range(1, n + 1)
    ]
    sales: list[dict[str, Any]] = []
    separators = ["-", "_", " "]
    sep_weights = [85, 10, 5]
    for i in range(1, m + 1):
        product_idx = rng.randint(1, n)
        customer_idx = rng.randint(1, n)
        sep = rng.choices(separators, weights=sep_weights, k=1)[0]
        sales.append(
            {
                "sale_id": _id("sale", i, width=9),
                "product_key": f"prod{sep}{product_idx:07d}",
                "customer_key": f"cust-{customer_idx:07d}",
                "qty": rng.randint(1, 8),
            }
        )

    row_counts = {
        "product_dim.csv": _write_csv(
            out_dir / "product_dim.csv",
            ["product_id", "product_name", "region_code"],
            products,
        ),
        "customer_dim.csv": _write_csv(
            out_dir / "customer_dim.csv",
            ["customer_id", "segment"],
            customers,
        ),
        "sales_fact.csv": _write_csv(
            out_dir / "sales_fact.csv",
            ["sale_id", "product_key", "customer_key", "qty"],
            sales,
        ),
    }

    manifest = {
        "scenario_name": "prefix_swap_namespace",
        "description": (
            "Derived replace-prefix challenge with namespace collision traps "
            "(prod-* should map to prd*, never to cust-*)."
        ),
        "challenge_columns": [
            "sales_fact.product_key (prod-0000123 style)",
            "product_dim.product_id (prd0000123 style)",
            "customer_dim.customer_id (cust-0000123 trap)",
        ],
        "ground_truth": {
            "core_relationships": [
                {
                    "from_table": "sales_fact",
                    "from_column": "product_key",
                    "to_table": "product_dim",
                    "to_column": "product_id",
                    "join_type": "derived",
                },
                {
                    "from_table": "sales_fact",
                    "from_column": "customer_key",
                    "to_table": "customer_dim",
                    "to_column": "customer_id",
                    "join_type": "direct",
                },
            ],
            "expected_rejections": [
                {
                    "from_table": "sales_fact",
                    "from_column": "product_key",
                    "to_table": "customer_dim",
                    "to_column": "customer_id",
                    "reason": "same numeric suffix, incompatible namespace",
                }
            ],
        },
    }
    _write_scenario_files(out_dir, manifest=manifest, row_counts=row_counts)
    return {"name": manifest["scenario_name"], "path": str(out_dir), "row_counts": row_counts}


def _scenario_strip_non_alnum(
    out_dir: Path,
    profile: Profile,
    rng: random.Random,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    n = profile.n_entities
    m = profile.n_events

    assets = [
        {"asset_id": _id("ast", i), "asset_type": rng.choice(["sensor", "gateway", "camera"])}
        for i in range(1, n + 1)
    ]
    vendors = [{"vendor_id": _id("vnd", i), "status": "active"} for i in range(1, n + 1)]
    symbols = ["#", "/", "."]
    events: list[dict[str, Any]] = []
    for i in range(1, m + 1):
        asset_idx = rng.randint(1, n)
        vendor_idx = rng.randint(1, n)
        symbol = rng.choices(symbols, weights=[75, 15, 10], k=1)[0]
        events.append(
            {
                "event_id": _id("evt", i, width=9),
                "asset_code": f"ast{symbol}{asset_idx:07d}",
                "vendor_ref": _id("vnd", vendor_idx),
                "severity": rng.choice(["low", "med", "high"]),
            }
        )

    row_counts = {
        "asset_registry.csv": _write_csv(
            out_dir / "asset_registry.csv",
            ["asset_id", "asset_type"],
            assets,
        ),
        "vendor_registry.csv": _write_csv(
            out_dir / "vendor_registry.csv",
            ["vendor_id", "status"],
            vendors,
        ),
        "sensor_events.csv": _write_csv(
            out_dir / "sensor_events.csv",
            ["event_id", "asset_code", "vendor_ref", "severity"],
            events,
        ),
    }

    manifest = {
        "scenario_name": "strip_non_alnum",
        "description": (
            "Identifier punctuation noise (ast#0000123) that should match canonical "
            "IDs only after strip_non_alnum."
        ),
        "challenge_columns": [
            "sensor_events.asset_code (ast#0000123 style)",
            "asset_registry.asset_id (ast0000123 style)",
            "vendor_registry.vendor_id (non-target namespace)",
        ],
        "ground_truth": {
            "core_relationships": [
                {
                    "from_table": "sensor_events",
                    "from_column": "asset_code",
                    "to_table": "asset_registry",
                    "to_column": "asset_id",
                    "join_type": "derived",
                },
                {
                    "from_table": "sensor_events",
                    "from_column": "vendor_ref",
                    "to_table": "vendor_registry",
                    "to_column": "vendor_id",
                    "join_type": "direct",
                },
            ],
            "expected_rejections": [],
        },
    }
    _write_scenario_files(out_dir, manifest=manifest, row_counts=row_counts)
    return {"name": manifest["scenario_name"], "path": str(out_dir), "row_counts": row_counts}


def _scenario_remove_prefix_numeric(
    out_dir: Path,
    profile: Profile,
    rng: random.Random,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    n = profile.n_entities
    m = profile.n_events

    payments = [{"payment_id": _num(i), "status": rng.choice(["posted", "failed"])} for i in range(1, n + 1)]
    refunds = [{"refund_id": _num(i), "status": rng.choice(["open", "closed"])} for i in range(1, n + 1)]
    ledger: list[dict[str, Any]] = []
    for i in range(1, m + 1):
        payment_idx = rng.randint(1, n)
        sep = "-" if rng.random() < 0.9 else "_"
        ledger.append(
            {
                "ledger_id": _id("led", i, width=9),
                "payment_key": f"pay{sep}{_num(payment_idx)}",
                "amount_cents": rng.randint(500, 50_000),
            }
        )

    row_counts = {
        "payment_dim.csv": _write_csv(
            out_dir / "payment_dim.csv",
            ["payment_id", "status"],
            payments,
        ),
        "refund_dim.csv": _write_csv(
            out_dir / "refund_dim.csv",
            ["refund_id", "status"],
            refunds,
        ),
        "ledger_events.csv": _write_csv(
            out_dir / "ledger_events.csv",
            ["ledger_id", "payment_key", "amount_cents"],
            ledger,
        ),
    }

    manifest = {
        "scenario_name": "remove_prefix_numeric",
        "description": (
            "Numeric IDs with deterministic remove-prefix transforms "
            "(pay-00001234 -> 00001234)."
        ),
        "challenge_columns": [
            "ledger_events.payment_key (pay-00001234 style)",
            "payment_dim.payment_id (00001234 style)",
            "refund_dim.refund_id (same digit domain trap)",
        ],
        "ground_truth": {
            "core_relationships": [
                {
                    "from_table": "ledger_events",
                    "from_column": "payment_key",
                    "to_table": "payment_dim",
                    "to_column": "payment_id",
                    "join_type": "derived",
                }
            ],
            "expected_rejections": [
                {
                    "from_table": "ledger_events",
                    "from_column": "payment_key",
                    "to_table": "refund_dim",
                    "to_column": "refund_id",
                    "reason": "different entity core despite identical numeric domain",
                }
            ],
        },
    }
    _write_scenario_files(out_dir, manifest=manifest, row_counts=row_counts)
    return {"name": manifest["scenario_name"], "path": str(out_dir), "row_counts": row_counts}


def _scenario_strip_hyphen_underscore(
    out_dir: Path,
    profile: Profile,
    rng: random.Random,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    n = profile.n_entities
    m = profile.n_events

    workspaces = [
        {"workspace_id": _id("wsp", i), "workspace_type": rng.choice(["prod", "stage", "dev"])}
        for i in range(1, n + 1)
    ]
    audits: list[dict[str, Any]] = []
    for i in range(1, m + 1):
        workspace_idx = rng.randint(1, n)
        num = f"{workspace_idx:07d}"
        audits.append(
            {
                "audit_id": _id("aud", i, width=9),
                "workspace_key": f"wsp-{num[:3]}_{num[3:]}",
                "action": rng.choice(["login", "deploy", "invite", "rotate_key"]),
            }
        )

    row_counts = {
        "workspace_dim.csv": _write_csv(
            out_dir / "workspace_dim.csv",
            ["workspace_id", "workspace_type"],
            workspaces,
        ),
        "audit_logs.csv": _write_csv(
            out_dir / "audit_logs.csv",
            ["audit_id", "workspace_key", "action"],
            audits,
        ),
    }

    manifest = {
        "scenario_name": "strip_hyphens_underscores",
        "description": (
            "Composite formatting noise where digits are split by mixed '-'/'_' separators "
            "and require strip_hyphens_underscores."
        ),
        "challenge_columns": [
            "audit_logs.workspace_key (wsp-123_4567 style)",
            "workspace_dim.workspace_id (wsp1234567 style)",
        ],
        "ground_truth": {
            "core_relationships": [
                {
                    "from_table": "audit_logs",
                    "from_column": "workspace_key",
                    "to_table": "workspace_dim",
                    "to_column": "workspace_id",
                    "join_type": "derived",
                }
            ],
            "expected_rejections": [],
        },
    }
    _write_scenario_files(out_dir, manifest=manifest, row_counts=row_counts)
    return {"name": manifest["scenario_name"], "path": str(out_dir), "row_counts": row_counts}


def _scenario_ambiguous_collision_guard(
    out_dir: Path,
    profile: Profile,
    rng: random.Random,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    n = profile.n_entities
    m = profile.n_events

    catalog = [
        {
            "part_id": _id("part", i),
            "part_legacy_id": _id("part", i),
            "part_shadow_id": _id("part", i),
        }
        for i in range(1, n + 1)
    ]
    batches = [{"batch_id": _id("batch", i), "batch_state": rng.choice(["open", "closed"])} for i in range(1, n + 1)]
    events: list[dict[str, Any]] = []
    for i in range(1, m + 1):
        idx = rng.randint(1, n)
        batch_idx = rng.randint(1, n)
        events.append(
            {
                "event_id": _id("evt", i, width=9),
                "part_ref": f"part#{idx:07d}",
                "batch_id": _id("batch", batch_idx),
            }
        )

    row_counts = {
        "catalog_dim.csv": _write_csv(
            out_dir / "catalog_dim.csv",
            ["part_id", "part_legacy_id", "part_shadow_id"],
            catalog,
        ),
        "batch_dim.csv": _write_csv(
            out_dir / "batch_dim.csv",
            ["batch_id", "batch_state"],
            batches,
        ),
        "part_events.csv": _write_csv(
            out_dir / "part_events.csv",
            ["event_id", "part_ref", "batch_id"],
            events,
        ),
    }

    manifest = {
        "scenario_name": "ambiguous_collision_guard",
        "description": (
            "Derived transform would match multiple target columns in the same table; "
            "ambiguity guard should reject part_ref -> catalog_* joins."
        ),
        "challenge_columns": [
            "part_events.part_ref (part#0000123 style)",
            "catalog_dim.part_id / part_legacy_id / part_shadow_id (overlapping targets)",
        ],
        "ground_truth": {
            "core_relationships": [
                {
                    "from_table": "part_events",
                    "from_column": "batch_id",
                    "to_table": "batch_dim",
                    "to_column": "batch_id",
                    "join_type": "direct",
                }
            ],
            "expected_rejections": [
                {
                    "from_table": "part_events",
                    "from_column": "part_ref",
                    "to_table": "catalog_dim",
                    "to_column": "part_id",
                    "reason": "ambiguous derived match across multiple target columns",
                }
            ],
        },
    }
    _write_scenario_files(out_dir, manifest=manifest, row_counts=row_counts)
    return {"name": manifest["scenario_name"], "path": str(out_dir), "row_counts": row_counts}


def _scenario_date_like_guard(
    out_dir: Path,
    profile: Profile,
    rng: random.Random,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    days = max(365, profile.n_entities // 20)
    start = date(2023, 1, 1)
    calendar_rows = []
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        calendar_rows.append({"calendar_date": d, "calendar_date_id": d})

    events: list[dict[str, Any]] = []
    for i in range(1, profile.n_events + 1):
        d = (start + timedelta(days=rng.randint(0, days - 1))).isoformat()
        events.append(
            {
                "event_id": _id("evt", i, width=9),
                "order_date": d,
                "order_date_id": f"dt-{d}",
            }
        )

    row_counts = {
        "calendar_dim.csv": _write_csv(
            out_dir / "calendar_dim.csv",
            ["calendar_date", "calendar_date_id"],
            calendar_rows,
        ),
        "order_events.csv": _write_csv(
            out_dir / "order_events.csv",
            ["event_id", "order_date", "order_date_id"],
            events,
        ),
    }

    manifest = {
        "scenario_name": "date_like_guard",
        "description": (
            "Date-like identifier columns that could look derivable (dt-YYYY-MM-DD) "
            "but must not use derived joins."
        ),
        "challenge_columns": [
            "order_events.order_date_id (dt-2023-01-01 style)",
            "calendar_dim.calendar_date_id (2023-01-01 style)",
        ],
        "ground_truth": {
            "core_relationships": [
                {
                    "from_table": "order_events",
                    "from_column": "order_date",
                    "to_table": "calendar_dim",
                    "to_column": "calendar_date",
                    "join_type": "direct",
                }
            ],
            "expected_rejections": [
                {
                    "from_table": "order_events",
                    "from_column": "order_date_id",
                    "to_table": "calendar_dim",
                    "to_column": "calendar_date_id",
                    "reason": "date-like columns should bypass derived transforms",
                }
            ],
        },
    }
    _write_scenario_files(out_dir, manifest=manifest, row_counts=row_counts)
    return {"name": manifest["scenario_name"], "path": str(out_dir), "row_counts": row_counts}


def _scenario_wide_budget_stress(
    out_dir: Path,
    profile: Profile,
    rng: random.Random,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    n = profile.n_entities
    m = profile.n_events

    entity_dim = [{"entity_id": _id("ent", i)} for i in range(1, n + 1)]
    account_dim = [{"account_id": _id("acc", i)} for i in range(1, n + 1)]

    noise_prefixes = [
        ("invoice_id", "inv"),
        ("subscription_key", "sub"),
        ("provider_id", "prv"),
        ("location_key", "loc"),
        ("sensor_id", "sns"),
        ("job_id", "job"),
        ("run_key", "run"),
        ("session_id", "ses"),
        ("trace_id", "trc"),
        ("ticket_key", "tkt"),
        ("request_id", "req"),
        ("pipeline_key", "ppl"),
    ]
    wide_rows: list[dict[str, Any]] = []
    for i in range(1, m + 1):
        entity_idx = rng.randint(1, n)
        account_idx = rng.randint(1, n)
        row: dict[str, Any] = {
            "event_id": _id("wev", i, width=9),
            "entity_ref": f"ent#{entity_idx:07d}",
            "account_id": _id("acc", account_idx),
        }
        for col_name, prefix in noise_prefixes:
            row[col_name] = _id(prefix, rng.randint(1, n))
        wide_rows.append(row)

    fieldnames = ["event_id", "entity_ref", "account_id"] + [name for name, _ in noise_prefixes]
    row_counts = {
        "entity_dim.csv": _write_csv(
            out_dir / "entity_dim.csv",
            ["entity_id"],
            entity_dim,
        ),
        "account_dim.csv": _write_csv(
            out_dir / "account_dim.csv",
            ["account_id"],
            account_dim,
        ),
        "wide_events.csv": _write_csv(
            out_dir / "wide_events.csv",
            fieldnames,
            wide_rows,
        ),
    }

    manifest = {
        "scenario_name": "wide_budget_stress",
        "description": (
            "Wide table with many identifier-like columns to stress anti-explosion budgets "
            "and still recover the intended derived join."
        ),
        "challenge_columns": [
            "wide_events.entity_ref (ent#0000123 style, derived target)",
            "wide_events.<many *_id/*_key columns> (noise for budget stress)",
            "entity_dim.entity_id and account_dim.account_id (one derived, one direct)",
        ],
        "ground_truth": {
            "core_relationships": [
                {
                    "from_table": "wide_events",
                    "from_column": "entity_ref",
                    "to_table": "entity_dim",
                    "to_column": "entity_id",
                    "join_type": "derived",
                },
                {
                    "from_table": "wide_events",
                    "from_column": "account_id",
                    "to_table": "account_dim",
                    "to_column": "account_id",
                    "join_type": "direct",
                },
            ],
            "expected_rejections": [],
        },
    }
    _write_scenario_files(out_dir, manifest=manifest, row_counts=row_counts)
    return {"name": manifest["scenario_name"], "path": str(out_dir), "row_counts": row_counts}


def _build_scenarios(config: Config) -> list[dict[str, Any]]:
    profile = PROFILES[config.profile]
    scenario_root = config.out_root
    if config.clean and scenario_root.exists():
        shutil.rmtree(scenario_root)
    scenario_root.mkdir(parents=True, exist_ok=True)

    base_rng = random.Random(config.seed)
    results: list[dict[str, Any]] = []
    scenario_builders = [
        _scenario_prefix_swap_namespace,
        _scenario_strip_non_alnum,
        _scenario_remove_prefix_numeric,
        _scenario_strip_hyphen_underscore,
        _scenario_ambiguous_collision_guard,
        _scenario_date_like_guard,
        _scenario_wide_budget_stress,
    ]

    for idx, builder in enumerate(scenario_builders, start=1):
        scenario_seed = base_rng.randint(1, 10_000_000) + idx
        scenario_rng = random.Random(scenario_seed)
        scenario_name = builder.__name__.replace("_scenario_", "")
        scenario_dir = scenario_root / scenario_name
        result = builder(
            out_dir=scenario_dir,
            profile=profile,
            rng=scenario_rng,
        )
        result["seed"] = scenario_seed
        results.append(result)
        print(f"Generated scenario: {result['name']} -> {scenario_dir}")
    return results


def _parse_args() -> Config:
    parser = argparse.ArgumentParser(
        description="Generate a suite of challenging datasets for derived-join performance testing."
    )
    parser.add_argument(
        "--out-root",
        type=Path,
        default=Path("perf_data") / "derived_challenge_datasets",
        help="Output root for scenario subfolders.",
    )
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES.keys()),
        default="small",
        help="Size profile for each generated scenario.",
    )
    parser.add_argument("--seed", type=int, default=20260225, help="Deterministic suite seed.")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete output root before generation.",
    )
    args = parser.parse_args()
    return Config(
        out_root=args.out_root,
        profile=args.profile,
        seed=args.seed,
        clean=bool(args.clean),
    )


def main() -> None:
    config = _parse_args()
    scenarios = _build_scenarios(config)
    summary = {
        "generator": "scripts/generate_smartjoin_derived_challenge_suite.py",
        "profile": config.profile,
        "seed": config.seed,
        "out_root": str(config.out_root),
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
    }
    summary_path = config.out_root / "suite_manifest.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote suite manifest: {summary_path}")


if __name__ == "__main__":
    main()
