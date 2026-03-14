"""Generate small focused regression datasets for derived-key join behavior."""

from __future__ import annotations

import argparse
import random
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from test_datasets.common import (
    CURRENCIES,
    build_manifest,
    dirty_key,
    idf,
    iso,
    maybe_missing,
    pick,
    token,
    write_csv,
    write_manifest,
)

PROFILE_BASE_ROWS: dict[str, int] = {
    "tiny": 40,
    "small": 120,
    "medium": 240,
    "large": 400,
}


@dataclass(frozen=True)
class Config:
    out_dir: Path
    seed: int
    profile: str
    base_rows: int
    pct_missing: float
    pct_duplicates: float
    pct_dirty_keys: float
    pct_derived_keys: float
    pct_derived_both_sides: float
    pct_inconsistent_types: float
    include_json: bool


def parse_args(argv: list[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(
        description="Generate deterministic derived-key regression datasets.",
    )
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--profile", choices=sorted(PROFILE_BASE_ROWS.keys()), default="small")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--pct-missing", type=float, default=0.02)
    parser.add_argument("--pct-duplicates", type=float, default=0.01)
    parser.add_argument("--pct-dirty-keys", type=float, default=0.04)
    parser.add_argument("--pct-derived-keys", type=float, default=0.2)
    parser.add_argument("--pct-derived-both-sides", type=float, default=0.1)
    parser.add_argument("--pct-inconsistent-types", type=float, default=0.03)
    parser.add_argument("--include-json", action="store_true", default=False)
    args = parser.parse_args(argv)

    out_dir = args.out_dir or (Path("perf_data") / "datasets" / f"derived_{args.profile}")
    return Config(
        out_dir=out_dir,
        seed=args.seed,
        profile=args.profile,
        base_rows=PROFILE_BASE_ROWS[args.profile],
        pct_missing=args.pct_missing,
        pct_duplicates=args.pct_duplicates,
        pct_dirty_keys=args.pct_dirty_keys,
        pct_derived_keys=args.pct_derived_keys,
        pct_derived_both_sides=args.pct_derived_both_sides,
        pct_inconsistent_types=args.pct_inconsistent_types,
        include_json=args.include_json,
    )


def generate_dataset(config: Config) -> dict[str, int]:
    rng = random.Random(config.seed)
    out_dir = config.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}

    base_n = config.base_rows
    epoch = date(2025, 1, 1)

    def maybe_dup(row: dict[str, Any]) -> Iterable[dict[str, Any]]:
        yield row
        if rng.random() < config.pct_duplicates:
            yield row.copy()

    # 1) Prefix swap: replace_prefix (prod -> prd)
    counts["prefix_swap_dim"] = write_csv(
        out_dir / "prefix_swap_dim.csv",
        ["product_id", "category", "currency"],
        (
            {
                "product_id": f"prd{i:05d}",
                "category": pick(rng, ["software", "service", "hardware"], [50, 35, 15]),
                "currency": pick(rng, CURRENCIES, [15, 75, 5, 5]),
            }
            for i in range(1, base_n + 1)
        ),
    )

    def prefix_swap_rows() -> Iterable[dict[str, Any]]:
        for i in range(1, (base_n * 3) + 1):
            product_num = rng.randint(1, base_n)
            key = f"prod-{product_num:05d}"
            if rng.random() < config.pct_dirty_keys * 0.2:
                key = dirty_key(rng, key)
            row = {
                "event_id": idf("EVT", i, 7),
                "product_key": key,
                "source_system": pick(rng, ["erp_a", "erp_b"], [70, 30]),
                "created_date": iso(epoch, rng.randint(0, 120)),
            }
            yield from maybe_dup(row)

    counts["prefix_swap_events"] = write_csv(
        out_dir / "prefix_swap_events.csv",
        ["event_id", "product_key", "source_system", "created_date"],
        prefix_swap_rows(),
    )

    # 2) strip_non_alnum
    counts["strip_non_alnum_dim"] = write_csv(
        out_dir / "strip_non_alnum_dim.csv",
        ["invoice_id", "status"],
        (
            {
                "invoice_id": f"INV{i:06d}",
                "status": pick(rng, ["open", "closed", "void"], [25, 70, 5]),
            }
            for i in range(1, base_n + 1)
        ),
    )

    def strip_non_alnum_rows() -> Iterable[dict[str, Any]]:
        for i in range(1, (base_n * 2) + 1):
            inv = rng.randint(1, base_n)
            row = {
                "invoice_event_id": idf("IE", i, 7),
                "invoice_ref": f"INV#{inv:06d}",
                "country": pick(rng, ["US", "DE", "GB"], [60, 25, 15]),
            }
            yield from maybe_dup(row)

    counts["strip_non_alnum_events"] = write_csv(
        out_dir / "strip_non_alnum_events.csv",
        ["invoice_event_id", "invoice_ref", "country"],
        strip_non_alnum_rows(),
    )

    # 3) remove_prefix numeric
    counts["remove_prefix_numeric_dim"] = write_csv(
        out_dir / "remove_prefix_numeric_dim.csv",
        ["payment_id", "payment_status"],
        (
            {
                "payment_id": i,
                "payment_status": pick(rng, ["captured", "failed", "refunded"], [72, 8, 20]),
            }
            for i in range(1, base_n + 1)
        ),
    )
    counts["refund_dim"] = write_csv(
        out_dir / "refund_dim.csv",
        ["refund_id", "reason"],
        (
            {
                "refund_id": i,
                "reason": pick(rng, ["cust_request", "fraud", "duplicate"], [65, 20, 15]),
            }
            for i in range(1, base_n + 1)
        ),
    )

    def remove_prefix_rows() -> Iterable[dict[str, Any]]:
        for i in range(1, (base_n * 3) + 1):
            pid = rng.randint(1, base_n)
            encoded = [f"pay-{pid:05d}", f"pay_{pid:05d}", f"PAY{pid:05d}"][i % 3]
            row = {
                "ledger_id": idf("LED", i, 7),
                "payment_key": encoded,
                "amount": round(max(1.0, rng.lognormvariate(3.0, 0.5)), 2),
            }
            yield from maybe_dup(row)

    counts["remove_prefix_numeric_events"] = write_csv(
        out_dir / "remove_prefix_numeric_events.csv",
        ["ledger_id", "payment_key", "amount"],
        remove_prefix_rows(),
    )

    # 4) Ambiguous collision guard
    amb_n = max(20, base_n // 2)
    counts["ambiguous_dim"] = write_csv(
        out_dir / "ambiguous_dim.csv",
        ["product_id", "product_alt_id", "product_legacy_id"],
        (
            {
                "product_id": f"prd{i:05d}",
                "product_alt_id": f"prd{i:05d}",
                "product_legacy_id": f"prd{i:05d}",
            }
            for i in range(1, amb_n + 1)
        ),
    )

    counts["ambiguous_events"] = write_csv(
        out_dir / "ambiguous_events.csv",
        ["event_id", "product_key", "status"],
        (
            {
                "event_id": idf("AE", i, 7),
                "product_key": f"prod-{((i - 1) % amb_n) + 1:05d}",
                "status": pick(rng, ["ok", "replayed"], [90, 10]),
            }
            for i in range(1, (amb_n * 3) + 1)
        ),
    )

    # 5) Date-like guard
    date_n = max(35, base_n // 2)
    calendar_dates = [iso(epoch, i) for i in range(date_n)]
    counts["calendar_dates"] = write_csv(
        out_dir / "calendar_dates.csv",
        ["calendar_date", "fiscal_week"],
        (
            {
                "calendar_date": dt,
                "fiscal_week": ((idx // 7) + 1),
            }
            for idx, dt in enumerate(calendar_dates)
        ),
    )
    counts["order_dates"] = write_csv(
        out_dir / "order_dates.csv",
        ["order_id", "order_date", "channel"],
        (
            {
                "order_id": idf("ORD", i, 7),
                "order_date": calendar_dates[(i - 1) % date_n],
                "channel": pick(rng, ["web", "mobile", "partner"], [60, 30, 10]),
            }
            for i in range(1, (date_n * 4) + 1)
        ),
    )

    # 6) Wide-budget stress
    stress_n = max(80, base_n)
    counts["wide_budget_dim"] = write_csv(
        out_dir / "wide_budget_dim.csv",
        ["item_id", "item_name", "active"],
        (
            {
                "item_id": f"x{i:05d}",
                "item_name": f"item-{token(rng, 6)}",
                "active": "true" if rng.random() > 0.08 else "false",
            }
            for i in range(1, stress_n + 1)
        ),
    )

    def wide_budget_rows() -> Iterable[dict[str, Any]]:
        for i in range(1, (stress_n * 3) + 1):
            key_num = ((i - 1) % stress_n) + 1
            base_key = f"x{key_num:05d}"
            row = {
                "event_id": idf("WBE", i, 7),
                "direct_item_id": base_key,
                "item_key_dash": f"x-{key_num:05d}",
                "item_key_hash": f"x#{key_num:05d}",
                "item_key_under": f"x_{key_num:05d}",
                "item_key_slash": f"x/{key_num:05d}",
                "item_key_spaced": f" x-{key_num:05d} ",
                "unrelated_id": f"cust-{key_num:05d}",
                "note": maybe_missing(rng, f"note-{token(rng, 5)}", config.pct_missing),
            }
            yield from maybe_dup(row)

    counts["wide_budget_events"] = write_csv(
        out_dir / "wide_budget_events.csv",
        [
            "event_id",
            "direct_item_id",
            "item_key_dash",
            "item_key_hash",
            "item_key_under",
            "item_key_slash",
            "item_key_spaced",
            "unrelated_id",
            "note",
        ],
        wide_budget_rows(),
    )

    return counts


def write_docs(config: Config, counts: dict[str, int]) -> None:
    out_dir = config.out_dir
    config_dict = asdict(config)
    config_dict["out_dir"] = str(config.out_dir)
    core_relationships = [
        {
            "case": "prefix_swap",
            "from_table": "prefix_swap_events",
            "from_column": "product_key",
            "to_table": "prefix_swap_dim",
            "to_column": "product_id",
            "expected_behavior": "derived_join",
            "expected_transform_hint": "replace_prefix(prod -> prd)",
        },
        {
            "case": "strip_non_alnum",
            "from_table": "strip_non_alnum_events",
            "from_column": "invoice_ref",
            "to_table": "strip_non_alnum_dim",
            "to_column": "invoice_id",
            "expected_behavior": "derived_join",
            "expected_transform_hint": "strip_non_alnum",
        },
        {
            "case": "remove_prefix_numeric",
            "from_table": "remove_prefix_numeric_events",
            "from_column": "payment_key",
            "to_table": "remove_prefix_numeric_dim",
            "to_column": "payment_id",
            "expected_behavior": "derived_join",
            "expected_transform_hint": "remove_prefix",
        },
        {
            "case": "date_like_guard",
            "from_table": "order_dates",
            "from_column": "order_date",
            "to_table": "calendar_dates",
            "to_column": "calendar_date",
            "expected_behavior": "direct_join_only",
            "expected_transform_hint": None,
        },
        {
            "case": "wide_budget_stress",
            "from_table": "wide_budget_events",
            "from_column": "direct_item_id",
            "to_table": "wide_budget_dim",
            "to_column": "item_id",
            "expected_behavior": "direct_join",
            "expected_transform_hint": None,
        },
    ]
    guard_expectations = [
        {
            "case": "ambiguous_collision_guard",
            "edge": "ambiguous_events.product_key -> ambiguous_dim.product_id",
            "expected": "blocked",
            "reason": "Multiple plausible derived targets in the same table.",
        },
        {
            "case": "ambiguous_collision_guard",
            "edge": "ambiguous_events.product_key -> ambiguous_dim.product_alt_id",
            "expected": "blocked",
            "reason": "Multiple plausible derived targets in the same table.",
        },
        {
            "case": "ambiguous_collision_guard",
            "edge": "ambiguous_events.product_key -> ambiguous_dim.product_legacy_id",
            "expected": "blocked",
            "reason": "Multiple plausible derived targets in the same table.",
        },
        {
            "case": "prefix_namespace_guard",
            "edge": "remove_prefix_numeric_events.payment_key -> refund_dim.refund_id",
            "expected": "blocked",
            "reason": "Identifier namespace mismatch (payment vs refund).",
        },
        {
            "case": "date_like_guard",
            "edge": "order_dates.order_date -> calendar_dates.calendar_date",
            "expected": "no_derived_transform",
            "reason": "Date-like columns should not use derived-key transforms.",
        },
    ]

    manifest = build_manifest(
        generator="scripts/test_datasets/domains/derived.py",
        config=config_dict,
        row_counts=counts,
        ground_truth={
            "core_relationships": core_relationships,
            "guard_expectations": guard_expectations,
            "regression_cases": [
                {
                    "name": "prefix_swap",
                    "goal": "Detect derived join with prefix replacement.",
                },
                {
                    "name": "strip_non_alnum",
                    "goal": "Detect derived join after stripping punctuation.",
                },
                {
                    "name": "remove_prefix_numeric",
                    "goal": "Detect derived join from prefixed string to numeric identifier.",
                },
                {
                    "name": "ambiguous_collision_guard",
                    "goal": "Reject ambiguous derived targets.",
                },
                {
                    "name": "date_like_guard",
                    "goal": "Avoid derived transforms on date-like columns.",
                },
                {
                    "name": "wide_budget_stress",
                    "goal": "Provide many candidate derived columns for budget stress checks.",
                },
            ],
        },
    )
    write_manifest(out_dir, manifest)
    legacy_readme = out_dir / "README.md"
    if legacy_readme.exists():
        legacy_readme.unlink()


def main(argv: list[str] | None = None) -> None:
    config = parse_args(argv)
    counts = generate_dataset(config)
    write_docs(config, counts)
    print(f"Generated dataset at: {config.out_dir.resolve()}")
    for table_name, count in counts.items():
        print(f"  - {table_name}: {count:,}")


if __name__ == "__main__":
    main()

