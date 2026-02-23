"""Generate deterministic SaaS billing/events test data for Smartjoin."""

from __future__ import annotations

import argparse
import csv
import json
import random
import string
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

COUNTRIES = ["US", "DE", "PL", "FR", "GB", "ES", "NL", "SE", "IT", "CZ"]
CURRENCIES = ["USD", "EUR", "PLN", "GBP"]
ACCOUNT_STATUSES = ["active", "trial", "churned", "suspended"]
SUB_STATUSES = ["trialing", "active", "past_due", "canceled"]
INVOICE_STATUSES = ["draft", "open", "paid", "void", "uncollectible"]
PAYMENT_STATUSES = ["authorized", "captured", "failed", "refunded"]
WORKSPACE_TYPES = ["prod", "staging", "dev", "sandbox"]
USER_ROLES = ["owner", "admin", "member", "viewer"]
PLAN_NAMES = ["starter", "growth", "scale", "enterprise"]
FEATURE_CATS = ["storage", "seats", "api", "compute", "support", "security"]


@dataclass(frozen=True)
class Profile:
    name: str
    n_accounts: int
    n_users: int
    n_workspaces: int
    n_plans: int
    n_features: int
    n_subscriptions: int
    n_invoices: int
    avg_invoice_lines: float
    n_usage_events: int


PROFILES: dict[str, Profile] = {
    "small": Profile("small", 8_000, 42_000, 17_000, 40, 600, 9_000, 70_000, 2.5, 200_000),
    "medium": Profile(
        "medium",
        24_000,
        130_000,
        54_000,
        80,
        1_800,
        30_000,
        240_000,
        2.9,
        700_000,
    ),
    "large": Profile(
        "large",
        80_000,
        420_000,
        170_000,
        180,
        6_000,
        120_000,
        1_100_000,
        3.2,
        2_500_000,
    ),
}


@dataclass(frozen=True)
class Config:
    out_dir: Path
    seed: int
    profile: str
    n_accounts: int
    n_users: int
    n_workspaces: int
    n_plans: int
    n_features: int
    n_subscriptions: int
    n_invoices: int
    avg_invoice_lines: float
    n_usage_events: int
    pct_missing: float
    pct_duplicates: float
    pct_dirty_keys: float
    pct_inconsistent_types: float
    include_json: bool
    max_json_events: int


def idf(prefix: str, value: int, width: int) -> str:
    return f"{prefix}{value:0{width}d}"


def iso(base: date, offset: int) -> str:
    return (base + timedelta(days=offset)).isoformat()


def pick(rng: random.Random, values: list[str], weights: list[int]) -> str:
    return rng.choices(values, weights=weights, k=1)[0]


def maybe_missing(rng: random.Random, value: Any, p: float) -> Any:
    return "" if rng.random() < p else value


def dirty_key(rng: random.Random, value: str) -> str:
    r = rng.random()
    if r < 0.33:
        return f" {value} "
    if r < 0.66:
        return value.lower()
    return value.zfill(len(value) + rng.randint(1, 3))


def token(rng: random.Random, n: int) -> str:
    return "".join(rng.choices(string.ascii_uppercase + string.digits, k=n))


def write_csv(path: Path, fields: list[str], rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def sample_lines(rng: random.Random, avg: float) -> int:
    p_stop = min(0.95, max(0.05, 1.0 / max(avg, 1.0)))
    count = 1
    while count < 10 and rng.random() > p_stop:
        count += 1
    return count


def parse_args() -> Config:
    parser = argparse.ArgumentParser(
        description="Generate deterministic SaaS billing/events test data."
    )
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--profile", choices=sorted(PROFILES.keys()), default="small")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-accounts", type=int, default=None)
    parser.add_argument("--n-users", type=int, default=None)
    parser.add_argument("--n-workspaces", type=int, default=None)
    parser.add_argument("--n-plans", type=int, default=None)
    parser.add_argument("--n-features", type=int, default=None)
    parser.add_argument("--n-subscriptions", type=int, default=None)
    parser.add_argument("--n-invoices", type=int, default=None)
    parser.add_argument("--avg-invoice-lines", type=float, default=None)
    parser.add_argument("--n-usage-events", type=int, default=None)
    parser.add_argument("--pct-missing", type=float, default=0.02)
    parser.add_argument("--pct-duplicates", type=float, default=0.01)
    parser.add_argument("--pct-dirty-keys", type=float, default=0.04)
    parser.add_argument("--pct-inconsistent-types", type=float, default=0.03)
    parser.add_argument("--include-json", action="store_true", default=False)
    parser.add_argument("--max-json-events", type=int, default=40_000)
    args = parser.parse_args()
    profile = PROFILES[args.profile]
    out_dir = args.out_dir or (Path("perf_data") / "datasets" / f"saas_{args.profile}")
    return Config(
        out_dir=out_dir,
        seed=args.seed,
        profile=args.profile,
        n_accounts=args.n_accounts or profile.n_accounts,
        n_users=args.n_users or profile.n_users,
        n_workspaces=args.n_workspaces or profile.n_workspaces,
        n_plans=args.n_plans or profile.n_plans,
        n_features=args.n_features or profile.n_features,
        n_subscriptions=args.n_subscriptions or profile.n_subscriptions,
        n_invoices=args.n_invoices or profile.n_invoices,
        avg_invoice_lines=args.avg_invoice_lines or profile.avg_invoice_lines,
        n_usage_events=args.n_usage_events or profile.n_usage_events,
        pct_missing=args.pct_missing,
        pct_duplicates=args.pct_duplicates,
        pct_dirty_keys=args.pct_dirty_keys,
        pct_inconsistent_types=args.pct_inconsistent_types,
        include_json=args.include_json,
        max_json_events=args.max_json_events,
    )


def generate_dataset(config: Config) -> dict[str, int]:
    rng = random.Random(config.seed)
    out_dir = config.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    base = date(2020, 1, 1)
    counts: dict[str, int] = {}

    def maybe_dup(row: dict[str, Any]) -> Iterable[dict[str, Any]]:
        yield row
        if rng.random() < config.pct_duplicates:
            yield row.copy()

    counts["accounts"] = write_csv(
        out_dir / "accounts.csv",
        ["account_id", "acct_id", "status", "country", "region_code", "created_date"],
        (
            dup
            for i in range(1, config.n_accounts + 1)
            for dup in maybe_dup(
                {
                    "account_id": idf("ACC", i, 8),
                    "acct_id": (idf("ACC", i, 8) if rng.random() > 0.17 else f"ACT{idf('', i, 8)}"),
                    "status": pick(rng, ACCOUNT_STATUSES, [70, 12, 10, 8]),
                    "country": pick(rng, COUNTRIES, [18, 12, 10, 9, 8, 7, 7, 7, 6, 6]),
                    "region_code": f"R{rng.randint(1, 40):02d}",
                    "created_date": iso(base, rng.randint(0, 1800)),
                }
            )
        ),
    )

    counts["users"] = write_csv(
        out_dir / "users.csv",
        ["user_id", "account_key_id", "role", "status", "country", "created_date"],
        (
            dup
            for i in range(1, config.n_users + 1)
            for dup in maybe_dup(
                {
                    "user_id": idf("USR", i, 9),
                    "account_key_id": (
                        dirty_key(rng, idf("ACC", rng.randint(1, config.n_accounts), 8))
                        if rng.random() < config.pct_dirty_keys
                        else idf("ACC", rng.randint(1, config.n_accounts), 8)
                    ),
                    "role": rng.choice(USER_ROLES),
                    "status": pick(rng, ["active", "inactive", "invited"], [86, 10, 4]),
                    "country": pick(rng, COUNTRIES, [18, 12, 10, 9, 8, 7, 7, 7, 6, 6]),
                    "created_date": iso(base, rng.randint(0, 1800)),
                }
            )
        ),
    )

    counts["workspaces"] = write_csv(
        out_dir / "workspaces.csv",
        [
            "workspace_id",
            "account_key_id",
            "workspace_type",
            "status",
            "region_code",
            "created_date",
        ],
        (
            dup
            for i in range(1, config.n_workspaces + 1)
            for dup in maybe_dup(
                {
                    "workspace_id": idf("WSP", i, 8),
                    "account_key_id": (
                        dirty_key(rng, idf("ACC", rng.randint(1, config.n_accounts), 8))
                        if rng.random() < config.pct_dirty_keys
                        else idf("ACC", rng.randint(1, config.n_accounts), 8)
                    ),
                    "workspace_type": rng.choice(WORKSPACE_TYPES),
                    "status": pick(rng, ["active", "inactive", "deleted"], [84, 10, 6]),
                    "region_code": f"R{rng.randint(1, 40):02d}",
                    "created_date": iso(base, rng.randint(0, 1800)),
                }
            )
        ),
    )

    counts["plans"] = write_csv(
        out_dir / "plans.csv",
        ["plan_id", "plan_name", "currency", "base_price", "status", "region_code"],
        (
            dup
            for i in range(1, config.n_plans + 1)
            for dup in maybe_dup(
                {
                    "plan_id": idf("PLN", i, 6),
                    "plan_name": rng.choice(PLAN_NAMES),
                    "currency": pick(rng, CURRENCIES, [35, 55, 5, 5]),
                    "base_price": round(max(9.0, rng.lognormvariate(3.2, 0.5)), 2),
                    "status": pick(rng, ["active", "retired"], [90, 10]),
                    "region_code": f"R{rng.randint(1, 40):02d}",
                }
            )
        ),
    )

    counts["features"] = write_csv(
        out_dir / "features.csv",
        ["feature_code", "category", "status", "currency", "created_date"],
        (
            dup
            for i in range(1, config.n_features + 1)
            for dup in maybe_dup(
                {
                    "feature_code": idf("FTR", i, 7),
                    "category": rng.choice(FEATURE_CATS),
                    "status": pick(rng, ["active", "beta", "retired"], [84, 10, 6]),
                    "currency": pick(rng, CURRENCIES, [35, 55, 5, 5]),
                    "created_date": iso(base, rng.randint(0, 1800)),
                }
            )
        ),
    )

    counts["subscriptions"] = write_csv(
        out_dir / "subscriptions.csv",
        [
            "subscription_id",
            "account_key_id",
            "plan_id",
            "status",
            "currency",
            "start_date",
            "end_date",
        ],
        (
            dup
            for i in range(1, config.n_subscriptions + 1)
            for dup in maybe_dup(
                {
                    "subscription_id": idf("SUB", i, 9),
                    "account_key_id": (
                        dirty_key(rng, idf("ACC", rng.randint(1, config.n_accounts), 8))
                        if rng.random() < config.pct_dirty_keys
                        else idf("ACC", rng.randint(1, config.n_accounts), 8)
                    ),
                    "plan_id": idf("PLN", rng.randint(1, config.n_plans), 6),
                    "status": pick(rng, SUB_STATUSES, [12, 68, 12, 8]),
                    "currency": pick(rng, CURRENCIES, [35, 55, 5, 5]),
                    "start_date": iso(base, rng.randint(0, 1800)),
                    "end_date": iso(base, rng.randint(1801, 2400)),
                }
            )
        ),
    )

    counts["invoices"] = write_csv(
        out_dir / "invoices.csv",
        [
            "invoice_id",
            "subscription_id",
            "account_id",
            "status",
            "currency",
            "invoice_number",
            "invoice_date",
            "total_amount",
        ],
        (
            dup
            for i in range(1, config.n_invoices + 1)
            for dup in maybe_dup(
                {
                    "invoice_id": idf("INV", i, 10),
                    "subscription_id": (
                        dirty_key(rng, idf("SUB", rng.randint(1, config.n_subscriptions), 9))
                        if rng.random() < config.pct_dirty_keys
                        else idf("SUB", rng.randint(1, config.n_subscriptions), 9)
                    ),
                    "account_id": idf("ACC", rng.randint(1, config.n_accounts), 8),
                    "status": pick(rng, INVOICE_STATUSES, [8, 18, 60, 8, 6]),
                    "currency": pick(rng, CURRENCIES, [35, 55, 5, 5]),
                    "invoice_number": (
                        i if rng.random() > config.pct_inconsistent_types else str(i)
                    ),
                    "invoice_date": iso(base, rng.randint(0, 2000)),
                    "total_amount": round(max(8.0, rng.lognormvariate(3.9, 0.8)), 2),
                }
            )
        ),
    )

    def invoice_line_rows() -> Iterable[dict[str, Any]]:
        for i in range(1, config.n_invoices + 1):
            invoice_id = idf("INV", i, 10)
            for line_no in range(1, sample_lines(rng, config.avg_invoice_lines) + 1):
                feature = idf("FTR", rng.randint(1, config.n_features), 7)
                if rng.random() < config.pct_dirty_keys:
                    feature = dirty_key(rng, feature)
                row = {
                    "invoice_id": invoice_id,
                    "line_no": line_no,
                    "feature_code": feature,
                    "quantity": rng.randint(1, 12),
                    "unit_price": round(max(1.0, rng.lognormvariate(2.5, 0.7)), 2),
                    "status": pick(rng, ["open", "closed", "void"], [35, 60, 5]),
                }
                yield from maybe_dup(row)

    counts["invoice_lines"] = write_csv(
        out_dir / "invoice_lines.csv",
        ["invoice_id", "line_no", "feature_code", "quantity", "unit_price", "status"],
        invoice_line_rows(),
    )

    counts["usage_events"] = write_csv(
        out_dir / "usage_events.csv",
        [
            "event_id",
            "workspace_key_id",
            "actor_user_id",
            "feature_code",
            "status",
            "event_date",
            "region_code",
        ],
        (
            dup
            for i in range(1, config.n_usage_events + 1)
            for dup in maybe_dup(
                {
                    "event_id": idf("EVT", i, 11),
                    "workspace_key_id": idf("WSP", rng.randint(1, config.n_workspaces), 8),
                    "actor_user_id": idf("USR", rng.randint(1, config.n_users), 9),
                    "feature_code": idf("FTR", rng.randint(1, config.n_features), 7),
                    "status": pick(rng, ["ok", "replayed", "dropped"], [90, 8, 2]),
                    "event_date": iso(base, rng.randint(0, 2000)),
                    "region_code": f"R{rng.randint(1, 40):02d}",
                }
            )
        ),
    )

    pay_count = 0
    refund_count = 0
    with (
        (out_dir / "payments.csv").open("w", newline="", encoding="utf-8") as pay_f,
        (out_dir / "refunds.csv").open("w", newline="", encoding="utf-8") as ref_f,
    ):
        pay_w = csv.DictWriter(
            pay_f,
            fieldnames=[
                "payment_id",
                "invoice_id",
                "status",
                "amount",
                "currency",
                "paid_date",
                "provider",
            ],
        )
        ref_w = csv.DictWriter(
            ref_f,
            fieldnames=["refund_id", "payment_id", "refund_amount", "created_date", "reason"],
        )
        pay_w.writeheader()
        ref_w.writeheader()
        for i in range(1, config.n_invoices + 1):
            if rng.random() < 0.08:
                continue
            invoice_id = idf("INV", i, 10)
            if rng.random() < config.pct_dirty_keys:
                invoice_id = dirty_key(rng, invoice_id)
            status = pick(rng, PAYMENT_STATUSES, [10, 72, 6, 12])
            paid = iso(base, rng.randint(0, 2100))
            pay = {
                "payment_id": idf("PAY", i, 10),
                "invoice_id": invoice_id,
                "status": status,
                "amount": round(max(5.0, rng.lognormvariate(3.7, 0.85)), 2),
                "currency": pick(rng, CURRENCIES, [35, 55, 5, 5]),
                "paid_date": paid,
                "provider": pick(rng, ["stripe", "adyen", "paypal"], [70, 20, 10]),
            }
            pay_w.writerow(pay)
            pay_count += 1
            if rng.random() < config.pct_duplicates:
                pay_w.writerow(pay)
                pay_count += 1
            if status in {"refunded"} or (status == "captured" and rng.random() < 0.04):
                refund = {
                    "refund_id": idf("REF", i, 10),
                    "payment_id": pay["payment_id"],
                    "refund_amount": round(max(1.0, rng.lognormvariate(2.8, 0.7)), 2),
                    "created_date": iso(date.fromisoformat(paid), rng.randint(0, 60)),
                    "reason": pick(
                        rng,
                        ["customer_request", "fraud", "duplicate", "billing_error"],
                        [55, 10, 15, 20],
                    ),
                }
                ref_w.writerow(refund)
                refund_count += 1
                if rng.random() < config.pct_duplicates:
                    ref_w.writerow(refund)
                    refund_count += 1

    counts["payments"] = pay_count
    counts["refunds"] = refund_count

    if config.include_json:
        json_n = min(config.max_json_events, config.n_usage_events)
        rows = []
        for i in range(1, json_n + 1):
            rows.append(
                {
                    "eventId": idf("EVT", i, 11),
                    "workspaceId": idf("WSP", rng.randint(1, config.n_workspaces), 8),
                    "userId": idf("USR", rng.randint(1, config.n_users), 9),
                    "meta": {
                        "status": pick(rng, ["ok", "replayed", "dropped"], [90, 8, 2]),
                        "region": f"R{rng.randint(1, 40):02d}",
                        "eventDate": iso(base, rng.randint(0, 2100)),
                    },
                }
            )
        (out_dir / "usage_events_nested.json").write_text(json.dumps(rows), encoding="utf-8")
        counts["usage_events_nested_json"] = json_n

    return counts


def write_docs(config: Config, counts: dict[str, int]) -> None:
    out_dir = config.out_dir
    config_dict = asdict(config)
    config_dict["out_dir"] = str(config.out_dir)
    core = [
        ("users", "account_key_id", "accounts", "account_id", True),
        ("workspaces", "account_key_id", "accounts", "account_id", True),
        ("subscriptions", "account_key_id", "accounts", "account_id", True),
        ("subscriptions", "plan_id", "plans", "plan_id", False),
        ("invoices", "subscription_id", "subscriptions", "subscription_id", True),
        ("invoice_lines", "invoice_id", "invoices", "invoice_id", False),
        ("invoice_lines", "feature_code", "features", "feature_code", True),
        ("payments", "invoice_id", "invoices", "invoice_id", True),
        ("refunds", "payment_id", "payments", "payment_id", False),
        ("usage_events", "workspace_key_id", "workspaces", "workspace_id", False),
        ("usage_events", "actor_user_id", "users", "user_id", False),
    ]
    if config.include_json:
        core.append(("usage_events_nested", "workspaceId", "workspaces", "workspace_id", False))
        core.append(("usage_events_nested", "userId", "users", "user_id", False))

    manifest = {
        "generator": "scripts/generate_smartjoin_saas_testdata.py",
        "config": config_dict,
        "row_counts": counts,
        "expected_joins": [f"{a}.{b} -> {c}.{d}" for a, b, c, d, _ in core],
        "expected_composite_keys": ["invoice_lines(invoice_id, line_no) near-unique"],
        "trap_columns": ["status", "country", "currency", "region_code", "created_date"],
        "ground_truth": {
            "core_relationships": [
                {
                    "from_table": a,
                    "from_column": b,
                    "to_table": c,
                    "to_column": d,
                    "relationship": "many_to_one",
                    "dirty_keys_present": dirty,
                }
                for a, b, c, d, dirty in core
            ],
            "composite_key_candidates": [
                {
                    "table": "invoice_lines",
                    "columns": ["invoice_id", "line_no"],
                    "notes": "Near-unique with controlled duplicates.",
                }
            ],
            "traps": {
                "shared_low_cardinality_columns": ["status", "country", "currency"],
                "date_like_columns": [
                    "created_date",
                    "updated_date",
                    "start_date",
                    "end_date",
                    "invoice_date",
                    "paid_date",
                    "event_date",
                ],
                "misleading_name_pairs": [
                    {
                        "left": "accounts.acct_id",
                        "right": "users.account_key_id",
                        "reason": "Similar account identifiers with alternate namespace.",
                    }
                ],
                "overlapping_value_traps": [
                    {
                        "columns": ["accounts.region_code", "plans.region_code"],
                        "value_domain": "R01-R40",
                        "expected_overlap": "very_high",
                    }
                ],
            },
        },
    }
    if config.include_json:
        manifest["ground_truth"]["traps"]["misleading_name_pairs"].append(
            {
                "left": "usage_events.workspace_key_id",
                "right": "usage_events_nested.workspaceId",
                "reason": "Naming style mismatch across CSV and JSON.",
            }
        )
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    lines = [
        "# Smartjoin SaaS Test Data",
        "",
        "Generated by `scripts/generate_smartjoin_saas_testdata.py`.",
        f"Profile: `{config.profile}`, Seed: `{config.seed}`",
        "",
        "## Row counts",
    ]
    lines.extend([f"- {name}: {count:,}" for name, count in counts.items()])
    lines.extend(["", "## Core True Relationships"])
    lines.extend([f"- {join}" for join in manifest["expected_joins"]])
    lines.extend(
        [
            "",
            "## Trap Signals (Should Not Be Primary Join Keys)",
            "- low-cardinality columns: status, country, currency",
            "- date-like columns shared across many tables",
            "- misleading ids: acct_id vs account_key_id",
            (
                "- true joins intentionally include different key names "
                "(account_key_id/workspace_key_id/actor_user_id)"
            ),
            "- overlapping region_code between unrelated dimensions",
        ]
    )
    (out_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    config = parse_args()
    counts = generate_dataset(config)
    write_docs(config, counts)
    print(f"Generated dataset at: {config.out_dir.resolve()}")
    for table_name, count in counts.items():
        print(f"  - {table_name}: {count:,}")


if __name__ == "__main__":
    main()
