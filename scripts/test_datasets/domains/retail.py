"""Generate deterministic, join-heavy test datasets for Smartjoin."""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from test_datasets.common import (
    COUNTRIES,
    CURRENCIES,
    derive_prefixed_numeric,
)
from test_datasets.common import (
    dirty_key as shared_dirty_key,
)
from test_datasets.common import (
    iso as shared_iso,
)
from test_datasets.common import (
    maybe_missing as shared_maybe_missing,
)
from test_datasets.common import (
    pick as shared_pick,
)
from test_datasets.common import (
    sample_lines as shared_sample_lines,
)
from test_datasets.common import (
    token as shared_token,
)
from test_datasets.common import (
    write_csv as shared_write_csv,
)

ORDER_STATUSES = ["created", "paid", "shipped", "delivered", "cancelled", "refunded"]
PAYMENT_STATUSES = ["authorized", "captured", "failed", "refunded", "partial_refund"]
SHIP_STATUSES = ["label_created", "in_transit", "delivered", "exception"]
CUSTOMER_TIERS = ["free", "basic", "pro", "enterprise"]
PRODUCT_CATEGORIES = ["widgets", "gadgets", "accessories", "services", "spares"]


@dataclass(frozen=True)
class SizeProfile:
    name: str
    n_customers: int
    n_products: int
    n_orders: int
    avg_items_per_order: float


PROFILES: dict[str, SizeProfile] = {
    "tiny": SizeProfile(
        name="tiny",
        n_customers=500,
        n_products=150,
        n_orders=1_200,
        avg_items_per_order=2.2,
    ),
    "small": SizeProfile(
        name="small",
        n_customers=20_000,
        n_products=6_000,
        n_orders=80_000,
        avg_items_per_order=2.8,
    ),
    "medium": SizeProfile(
        name="medium",
        n_customers=60_000,
        n_products=18_000,
        n_orders=240_000,
        avg_items_per_order=3.2,
    ),
    "large": SizeProfile(
        name="large",
        n_customers=180_000,
        n_products=60_000,
        n_orders=1_000_000,
        avg_items_per_order=3.4,
    ),
}


@dataclass(frozen=True)
class Config:
    out_dir: Path
    seed: int
    profile: str
    n_customers: int
    n_products: int
    n_orders: int
    avg_items_per_order: float
    pct_missing: float
    pct_duplicates: float
    pct_dirty_keys: float
    pct_derived_keys: float
    pct_derived_both_sides: float
    pct_inconsistent_types: float
    include_json: bool
    max_json_orders: int


def build_core_table_specs() -> list[dict[str, Any]]:
    """Return table-level relationship expectations for the generated dataset."""
    return [
        {"table": "customers", "file": "customers.csv", "primary_key": ["customer_id"]},
        {"table": "products", "file": "products.csv", "primary_key": ["product_id"]},
        {
            "table": "orders",
            "file": "orders.csv",
            "primary_key": ["order_id"],
            "foreign_keys": [
                {"columns": ["customer_key_id"], "references": "customers.customer_id"}
            ],
        },
        {
            "table": "order_items",
            "file": "order_items.csv",
            "primary_key_candidate": ["order_id", "line_no"],
            "foreign_keys": [
                {"columns": ["order_id"], "references": "orders.order_id"},
                {"columns": ["product_id"], "references": "products.product_id"},
            ],
        },
        {
            "table": "payments",
            "file": "payments.csv",
            "foreign_keys": [{"columns": ["order_key_id"], "references": "orders.order_id"}],
        },
        {
            "table": "shipments",
            "file": "shipments.csv",
            "foreign_keys": [{"columns": ["order_key_id"], "references": "orders.order_id"}],
        },
        {
            "table": "refunds",
            "file": "refunds.csv",
            "foreign_keys": [{"columns": ["payment_key_id"], "references": "payments.payment_id"}],
        },
        {"table": "promotions", "file": "promotions.csv", "primary_key": ["promo_code"]},
        {
            "table": "order_promotions",
            "file": "order_promotions.csv",
            "bridge_for": ["orders", "promotions"],
            "composite_key_candidate": ["order_key_id", "promo_code"],
            "foreign_keys": [
                {"columns": ["order_key_id"], "references": "orders.order_id"},
                {"columns": ["promo_code"], "references": "promotions.promo_code"},
            ],
        },
    ]


def build_core_relationships(include_json: bool) -> list[dict[str, Any]]:
    """Return explicit core joins that should be detected."""
    relationships = [
        {
            "from_table": "orders",
            "from_column": "customer_key_id",
            "to_table": "customers",
            "to_column": "customer_id",
            "relationship": "many_to_one",
            "dirty_keys_present": True,
            "join_type": "derived_mixed",
            "derived_side": "from_table_only",
        },
        {
            "from_table": "order_items",
            "from_column": "order_id",
            "to_table": "orders",
            "to_column": "order_id",
            "relationship": "many_to_one",
            "dirty_keys_present": False,
            "join_type": "direct",
        },
        {
            "from_table": "order_items",
            "from_column": "product_id",
            "to_table": "products",
            "to_column": "product_id",
            "relationship": "many_to_one",
            "dirty_keys_present": True,
            "join_type": "derived_mixed",
            "derived_side": "from_table_only",
        },
        {
            "from_table": "payments",
            "from_column": "order_key_id",
            "to_table": "orders",
            "to_column": "order_id",
            "relationship": "many_to_one",
            "dirty_keys_present": True,
            "join_type": "derived_mixed",
            "derived_side": "from_table_only",
        },
        {
            "from_table": "refunds",
            "from_column": "payment_key_id",
            "to_table": "payments",
            "to_column": "payment_id",
            "relationship": "many_to_one",
            "dirty_keys_present": False,
            "join_type": "derived_mixed",
            "derived_side": "both_tables",
        },
        {
            "from_table": "shipments",
            "from_column": "order_key_id",
            "to_table": "orders",
            "to_column": "order_id",
            "relationship": "many_to_one",
            "dirty_keys_present": True,
            "join_type": "derived_mixed",
            "derived_side": "from_table_only",
        },
        {
            "from_table": "order_promotions",
            "from_column": "order_key_id",
            "to_table": "orders",
            "to_column": "order_id",
            "relationship": "many_to_one",
            "dirty_keys_present": False,
            "join_type": "derived_mixed",
            "derived_side": "from_table_only",
        },
        {
            "from_table": "order_promotions",
            "from_column": "promo_code",
            "to_table": "promotions",
            "to_column": "promo_code",
            "relationship": "many_to_one",
            "dirty_keys_present": False,
            "join_type": "direct",
        },
    ]
    if include_json:
        relationships.append(
            {
                "from_table": "orders_nested",
                "from_column": "customerId",
                "to_table": "customers",
                "to_column": "customer_id",
                "relationship": "many_to_one",
                "dirty_keys_present": False,
                "notes": "Naming trap due to camelCase in JSON.",
            }
        )
    return relationships


def build_trap_summary(include_json: bool) -> dict[str, Any]:
    """Return trap metadata for testing false-positive resistance."""
    misleading_names = [
        {
            "left": "customers.cust_id",
            "right": "orders.customer_key_id",
            "reason": "Similar semantics but different key encoding.",
        }
    ]
    if include_json:
        misleading_names.append(
            {
                "left": "orders.customer_key_id",
                "right": "orders_nested.customerId",
                "reason": "Same entity represented with different naming convention.",
            }
        )
    return {
        "shared_low_cardinality_columns": ["country", "status", "currency"],
        "date_like_columns": [
            "created_date",
            "updated_date",
            "shipped_date",
            "delivered_date",
            "start_date",
            "end_date",
            "applied_date",
        ],
        "misleading_name_pairs": misleading_names,
        "overlapping_value_traps": [
            {
                "columns": ["customers.region_code", "products.region_code"],
                "value_domain": "R01-R30",
                "expected_overlap": "very_high",
                "reason": "Shared region vocabulary can create false positive joins.",
            }
        ],
    }


def parse_args(argv: list[str] | None = None) -> Config:
    """Build generator configuration from CLI args."""
    parser = argparse.ArgumentParser(
        description="Generate deterministic relational test data for Smartjoin."
    )
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--profile", choices=sorted(PROFILES.keys()), default="medium")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-customers", type=int, default=None)
    parser.add_argument("--n-products", type=int, default=None)
    parser.add_argument("--n-orders", type=int, default=None)
    parser.add_argument("--avg-items-per-order", type=float, default=None)
    parser.add_argument("--pct-missing", type=float, default=0.02)
    parser.add_argument("--pct-duplicates", type=float, default=0.01)
    parser.add_argument("--pct-dirty-keys", type=float, default=0.04)
    parser.add_argument("--pct-derived-keys", type=float, default=0.2)
    parser.add_argument("--pct-derived-both-sides", type=float, default=0.1)
    parser.add_argument("--pct-inconsistent-types", type=float, default=0.03)
    parser.add_argument("--include-json", action="store_true", default=False)
    parser.add_argument("--max-json-orders", type=int, default=40_000)
    args = parser.parse_args(argv)

    profile = PROFILES[args.profile]
    out_dir = args.out_dir or (Path("perf_data") / "datasets" / f"smartjoin_{args.profile}")
    return Config(
        out_dir=out_dir,
        seed=args.seed,
        profile=args.profile,
        n_customers=args.n_customers or profile.n_customers,
        n_products=args.n_products or profile.n_products,
        n_orders=args.n_orders or profile.n_orders,
        avg_items_per_order=args.avg_items_per_order or profile.avg_items_per_order,
        pct_missing=args.pct_missing,
        pct_duplicates=args.pct_duplicates,
        pct_dirty_keys=args.pct_dirty_keys,
        pct_derived_keys=args.pct_derived_keys,
        pct_derived_both_sides=args.pct_derived_both_sides,
        pct_inconsistent_types=args.pct_inconsistent_types,
        include_json=args.include_json,
        max_json_orders=args.max_json_orders,
    )


def make_customer_id(value: int) -> str:
    return f"C{value:07d}"


def make_product_id(value: int) -> str:
    return f"P{value:06d}"


def make_order_id(value: int) -> str:
    return f"O{value:09d}"


def maybe_derived_id(
    rng: random.Random,
    value: str,
    *,
    probability: float,
    prefix_override: str,
    styles: tuple[str, ...] = ("dash_lower", "underscore_upper", "hash_lower"),
) -> str:
    if rng.random() >= probability:
        return value
    style = rng.choice(list(styles))
    return derive_prefixed_numeric(value, style=style, prefix_override=prefix_override)


def pick_weighted(rng: random.Random, values: list[str], weights: list[int]) -> str:
    return shared_pick(rng, values, weights)


def maybe_missing(rng: random.Random, value: Any, probability: float) -> Any:
    return shared_maybe_missing(rng, value, probability)


def dirty_key(rng: random.Random, value: str) -> str:
    return shared_dirty_key(rng, value)


def rand_token(rng: random.Random, length: int) -> str:
    return shared_token(rng, length)


def iso_date(base_date: date, offset_days: int) -> str:
    return shared_iso(base_date, offset_days)


def write_csv_rows(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> int:
    return shared_write_csv(path, fieldnames, rows)


def sample_item_count(rng: random.Random, avg_target: float) -> int:
    """
    Sample a bounded line-item count with average near `avg_target`.

    A geometric-like process gives long tails and realistic skew.
    """
    return shared_sample_lines(rng, avg_target, max_lines=12)


def generate_dataset(config: Config) -> dict[str, int]:
    """Generate all dataset files and return per-table row counts."""
    rng = random.Random(config.seed)
    out_dir = config.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    base_date = date(2022, 1, 1)

    first_names = ["Anna", "Jan", "Ola", "Tom", "Sara", "Marek", "Eva", "Noah", "Liam", "Mia"]
    last_names = [
        "Nowak",
        "Kowalski",
        "Smith",
        "Brown",
        "Muller",
        "Dubois",
        "Garcia",
        "Rossi",
        "Novak",
        "Svensson",
    ]
    email_domains = ["example.com", "mail.com", "startup.io", "company.co"]
    channels = ["web", "mobile", "partner", "unknown"]
    payment_providers = ["stripe", "adyen", "paypal"]
    carriers = ["dhl", "ups", "fedex", "gls", "inpost"]

    row_counts: dict[str, int] = {}

    def maybe_dup(row: dict[str, Any]) -> Iterable[dict[str, Any]]:
        yield row
        if rng.random() < config.pct_duplicates:
            yield row.copy()

    # customers.csv
    def customer_rows() -> Iterable[dict[str, Any]]:
        for i in range(1, config.n_customers + 1):
            customer_id = make_customer_id(i)
            first_name = rng.choice(first_names)
            last_name = rng.choice(last_names)
            email = f"{first_name}.{last_name}@{rng.choice(email_domains)}".lower()
            row = {
                "customer_id": customer_id,
                "cust_id": customer_id if rng.random() > 0.15 else customer_id.replace("C", "CUS"),
                "first_name": first_name,
                "last_name": last_name,
                "email": maybe_missing(rng, email, config.pct_missing),
                "phone": maybe_missing(
                    rng,
                    f"+{rng.randint(1, 99)}{rng.randint(100000000, 999999999)}",
                    config.pct_missing,
                ),
                "country": pick_weighted(rng, COUNTRIES, [18, 12, 10, 9, 8, 7, 7, 7, 6, 6]),
                "region_code": f"R{rng.randint(1, 30):02d}",
                "tier": pick_weighted(rng, CUSTOMER_TIERS, [55, 25, 15, 5]),
                "created_date": iso_date(base_date, rng.randint(0, 900)),
            }
            yield from maybe_dup(row)

    row_counts["customers"] = write_csv_rows(
        out_dir / "customers.csv",
        [
            "customer_id",
            "cust_id",
            "first_name",
            "last_name",
            "email",
            "phone",
            "country",
            "region_code",
            "tier",
            "created_date",
        ],
        customer_rows(),
    )

    # products.csv
    def product_rows() -> Iterable[dict[str, Any]]:
        for i in range(1, config.n_products + 1):
            row = {
                "product_id": make_product_id(i),
                "sku": f"SKU-{rand_token(rng, 8)}",
                "name": (
                    f"{pick_weighted(rng, PRODUCT_CATEGORIES, [35, 25, 15, 15, 10])}"
                    f"-{rand_token(rng, 6)}"
                ),
                "category": pick_weighted(rng, PRODUCT_CATEGORIES, [35, 25, 15, 15, 10]),
                "list_price": round(max(1.0, rng.lognormvariate(3.0, 0.5)), 2),
                "currency": pick_weighted(rng, CURRENCIES, [35, 55, 5, 5]),
                "active": "true" if rng.random() > 0.05 else "false",
                "created_date": iso_date(base_date, rng.randint(0, 900)),
                "region_code": f"R{rng.randint(1, 30):02d}",
            }
            yield from maybe_dup(row)

    row_counts["products"] = write_csv_rows(
        out_dir / "products.csv",
        [
            "product_id",
            "sku",
            "name",
            "category",
            "list_price",
            "currency",
            "active",
            "created_date",
            "region_code",
        ],
        product_rows(),
    )

    # orders.csv
    def order_rows() -> Iterable[dict[str, Any]]:
        for i in range(1, config.n_orders + 1):
            customer_id = make_customer_id(rng.randint(1, config.n_customers))
            customer_id = maybe_derived_id(
                rng,
                customer_id,
                probability=config.pct_derived_keys,
                prefix_override="cust",
            )
            if rng.random() < config.pct_dirty_keys:
                customer_id = dirty_key(rng, customer_id)
            order_number: Any = i
            if rng.random() < config.pct_inconsistent_types:
                order_number = str(i)
            created = iso_date(base_date, rng.randint(0, 1000))
            updated = iso_date(date.fromisoformat(created), rng.randint(0, 30))
            row = {
                "order_id": make_order_id(i),
                "customer_key_id": customer_id,
                "order_number": order_number,
                "status": pick_weighted(rng, ORDER_STATUSES, [10, 30, 20, 25, 10, 5]),
                "country": pick_weighted(rng, COUNTRIES, [18, 12, 10, 9, 8, 7, 7, 7, 6, 6]),
                "currency": pick_weighted(rng, CURRENCIES, [30, 60, 5, 5]),
                "created_date": created,
                "updated_date": updated,
                "channel": pick_weighted(rng, channels, [55, 25, 15, 5]),
            }
            yield from maybe_dup(row)

    row_counts["orders"] = write_csv_rows(
        out_dir / "orders.csv",
        [
            "order_id",
            "customer_key_id",
            "order_number",
            "status",
            "country",
            "currency",
            "created_date",
            "updated_date",
            "channel",
        ],
        order_rows(),
    )

    # order_items.csv
    def order_item_rows() -> Iterable[dict[str, Any]]:
        for order_index in range(1, config.n_orders + 1):
            order_id = make_order_id(order_index)
            line_count = sample_item_count(rng, config.avg_items_per_order)
            for line_no in range(1, line_count + 1):
                product_id = make_product_id(rng.randint(1, config.n_products))
                product_id = maybe_derived_id(
                    rng,
                    product_id,
                    probability=config.pct_derived_keys * 0.6,
                    prefix_override="prd",
                )
                if rng.random() < config.pct_dirty_keys:
                    product_id = dirty_key(rng, product_id)
                row = {
                    "order_id": order_id,
                    "line_no": line_no,
                    "product_id": product_id,
                    "quantity": max(1, int(round(rng.lognormvariate(0.0, 0.7)))),
                    "unit_price": round(max(1.0, rng.lognormvariate(3.0, 0.6)), 2),
                    "discount_pct": round(min(0.8, max(0.0, rng.betavariate(2, 12))), 3),
                    "status": pick_weighted(rng, ["ok", "backorder", "cancelled"], [88, 10, 2]),
                }
                yield from maybe_dup(row)

    row_counts["order_items"] = write_csv_rows(
        out_dir / "order_items.csv",
        [
            "order_id",
            "line_no",
            "product_id",
            "quantity",
            "unit_price",
            "discount_pct",
            "status",
        ],
        order_item_rows(),
    )

    # payments.csv + refunds.csv
    payment_count = 0
    refund_count = 0
    with (
        (out_dir / "payments.csv").open("w", newline="", encoding="utf-8") as payments_file,
        (out_dir / "refunds.csv").open("w", newline="", encoding="utf-8") as refunds_file,
    ):
        pay_writer = csv.DictWriter(
            payments_file,
            fieldnames=[
                "payment_id",
                "order_key_id",
                "status",
                "amount",
                "currency",
                "created_date",
                "provider",
            ],
        )
        ref_writer = csv.DictWriter(
            refunds_file,
            fieldnames=["refund_id", "payment_key_id", "refund_amount", "created_date", "reason"],
        )
        pay_writer.writeheader()
        ref_writer.writeheader()

        for i in range(1, config.n_orders + 1):
            if rng.random() < 0.06:
                continue
            order_id = maybe_derived_id(
                rng,
                make_order_id(i),
                probability=config.pct_derived_keys,
                prefix_override="ord",
            )
            if rng.random() < config.pct_dirty_keys:
                order_id = dirty_key(rng, order_id)
            payment_id_canonical = f"PAY{i:010d}"
            payment_id = payment_id_canonical
            refund_payment_key = payment_id_canonical
            if rng.random() < config.pct_derived_both_sides:
                payment_id = maybe_derived_id(
                    rng,
                    payment_id_canonical,
                    probability=1.0,
                    prefix_override="pay",
                    styles=("dash_lower", "hash_lower"),
                )
                refund_payment_key = maybe_derived_id(
                    rng,
                    payment_id_canonical,
                    probability=1.0,
                    prefix_override="payment",
                    styles=("underscore_upper", "slash_lower", "space_dash"),
                )
                if refund_payment_key == payment_id:
                    refund_payment_key = derive_prefixed_numeric(
                        payment_id_canonical,
                        style="underscore_upper",
                        prefix_override="payment",
                    )
            status = pick_weighted(rng, PAYMENT_STATUSES, [10, 70, 5, 10, 5])
            amount = round(max(1.0, rng.lognormvariate(3.2, 0.7)), 2)
            created = iso_date(base_date, rng.randint(0, 1000))
            payment_row = {
                "payment_id": payment_id,
                "order_key_id": order_id,
                "status": status,
                "amount": amount,
                "currency": pick_weighted(rng, CURRENCIES, [30, 60, 5, 5]),
                "created_date": created,
                "provider": pick_weighted(rng, payment_providers, [70, 20, 10]),
            }
            pay_writer.writerow(payment_row)
            payment_count += 1
            if rng.random() < config.pct_duplicates:
                pay_writer.writerow(payment_row)
                payment_count += 1

            should_refund = status in {"refunded", "partial_refund"} or (
                status == "captured" and rng.random() < 0.03
            )
            if should_refund:
                refund_amount = (
                    amount if status == "refunded" else round(amount * rng.uniform(0.1, 0.9), 2)
                )
                refund_row = {
                    "refund_id": f"REF{i:010d}",
                    "payment_key_id": refund_payment_key,
                    "refund_amount": refund_amount,
                    "created_date": iso_date(date.fromisoformat(created), rng.randint(0, 60)),
                    "reason": pick_weighted(
                        rng,
                        ["customer_request", "fraud", "logistics", "duplicate"],
                        [55, 10, 25, 10],
                    ),
                }
                ref_writer.writerow(refund_row)
                refund_count += 1
                if rng.random() < config.pct_duplicates:
                    ref_writer.writerow(refund_row)
                    refund_count += 1

    row_counts["payments"] = payment_count
    row_counts["refunds"] = refund_count

    # shipments.csv
    def shipment_rows() -> Iterable[dict[str, Any]]:
        n_shipments = int(config.n_orders * 0.72)
        for i in range(1, n_shipments + 1):
            shipped_date = iso_date(base_date, rng.randint(0, 1000))
            delivered_date = iso_date(date.fromisoformat(shipped_date), rng.randint(1, 12))
            order_id = maybe_derived_id(
                rng,
                make_order_id(rng.randint(1, config.n_orders)),
                probability=config.pct_derived_keys,
                prefix_override="ord",
            )
            if rng.random() < config.pct_dirty_keys:
                order_id = dirty_key(rng, order_id)
            row = {
                "shipment_id": f"SHP{i:010d}",
                "order_key_id": order_id,
                "status": pick_weighted(rng, SHIP_STATUSES, [15, 45, 35, 5]),
                "carrier": pick_weighted(rng, carriers, [20, 25, 20, 15, 20]),
                "shipped_date": shipped_date,
                "delivered_date": delivered_date,
                "country": pick_weighted(rng, COUNTRIES, [18, 12, 10, 9, 8, 7, 7, 7, 6, 6]),
            }
            yield from maybe_dup(row)

    row_counts["shipments"] = write_csv_rows(
        out_dir / "shipments.csv",
        [
            "shipment_id",
            "order_key_id",
            "status",
            "carrier",
            "shipped_date",
            "delivered_date",
            "country",
        ],
        shipment_rows(),
    )

    # promotions.csv
    promo_count = 500
    promo_codes: list[str] = []

    def promotion_rows() -> Iterable[dict[str, Any]]:
        for _ in range(promo_count):
            promo_code = f"PROMO{rand_token(rng, 6)}"
            promo_codes.append(promo_code)
            row = {
                "promo_code": promo_code,
                "description": f"Campaign {rand_token(rng, 8)}",
                "discount_type": pick_weighted(rng, ["pct", "fixed"], [75, 25]),
                "discount_value": round(rng.uniform(5.0, 30.0), 2),
                "active": "true" if rng.random() > 0.2 else "false",
                "start_date": iso_date(base_date, rng.randint(0, 900)),
                "end_date": iso_date(base_date, rng.randint(901, 1200)),
            }
            yield row

    row_counts["promotions"] = write_csv_rows(
        out_dir / "promotions.csv",
        [
            "promo_code",
            "description",
            "discount_type",
            "discount_value",
            "active",
            "start_date",
            "end_date",
        ],
        promotion_rows(),
    )

    # order_promotions.csv
    def order_promotion_rows() -> Iterable[dict[str, Any]]:
        n_rows = int(config.n_orders * 0.35)
        for _ in range(n_rows):
            order_key = maybe_derived_id(
                rng,
                make_order_id(rng.randint(1, config.n_orders)),
                probability=config.pct_derived_keys,
                prefix_override="ord",
            )
            row = {
                "order_key_id": order_key,
                "promo_code": rng.choice(promo_codes),
                "applied_date": iso_date(base_date, rng.randint(0, 1000)),
            }
            yield from maybe_dup(row)

    row_counts["order_promotions"] = write_csv_rows(
        out_dir / "order_promotions.csv",
        ["order_key_id", "promo_code", "applied_date"],
        order_promotion_rows(),
    )

    # optional orders_nested.json
    if config.include_json:
        json_rows = min(config.max_json_orders, config.n_orders)
        nested_rows = []
        for i in range(1, json_rows + 1):
            nested_rows.append(
                {
                    "orderId": make_order_id(i),
                    "customerId": make_customer_id(rng.randint(1, config.n_customers)),
                    "meta": {
                        "status": pick_weighted(rng, ORDER_STATUSES, [10, 30, 20, 25, 10, 5]),
                        "country": pick_weighted(rng, COUNTRIES, [18, 12, 10, 9, 8, 7, 7, 7, 6, 6]),
                        "createdAt": iso_date(base_date, rng.randint(0, 1000)),
                    },
                    "tags": rng.sample(
                        ["new", "vip", "trial", "b2b", "b2c", "promo"],
                        k=rng.randint(0, 3),
                    ),
                }
            )
        with (out_dir / "orders_nested.json").open("w", encoding="utf-8") as handle:
            json.dump(nested_rows, handle)
        row_counts["orders_nested_json"] = json_rows

    return row_counts


def write_dataset_docs(config: Config, row_counts: dict[str, int]) -> None:
    """Write dataset README + machine-readable manifest."""
    out_dir = config.out_dir
    config_dict = asdict(config)
    config_dict["out_dir"] = str(config.out_dir)
    core_relationships = build_core_relationships(include_json=config.include_json)
    traps = build_trap_summary(include_json=config.include_json)
    core_tables = build_core_table_specs()
    expected_join_strings = [
        (
            f"{relationship['from_table']}.{relationship['from_column']} -> "
            f"{relationship['to_table']}.{relationship['to_column']}"
        )
        for relationship in core_relationships
    ]
    manifest = {
        "generator": "scripts/test_datasets/domains/retail.py",
        "config": config_dict,
        "row_counts": row_counts,
        "expected_joins": expected_join_strings,
        "expected_composite_keys": [
            "order_items(order_id, line_no) near-unique, with controlled duplicates",
        ],
        "trap_columns": ["country", "status", "currency", "region_code", "created_date"],
        "ground_truth": {
            "core_tables": core_tables,
            "core_relationships": core_relationships,
            "composite_key_candidates": [
                {
                    "table": "order_items",
                    "columns": ["order_id", "line_no"],
                    "notes": "Near-unique with controlled duplicates.",
                }
            ],
            "traps": traps,
        },
    }

    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# Smartjoin Performance Test Data",
        "",
        f"Generated by `scripts/test_datasets/domains/retail.py` with seed `{config.seed}`.",
        f"Profile: `{config.profile}`",
        "",
        "## Row counts",
    ]
    for name, count in row_counts.items():
        lines.append(f"- {name}: {count:,}")
    lines.extend(["", "## Core True Relationships"])
    for relationship in core_relationships:
        lines.append(
            "- "
            f"{relationship['from_table']}.{relationship['from_column']} -> "
            f"{relationship['to_table']}.{relationship['to_column']}"
        )
    lines.extend(
        [
            "",
            "## Trap Signals (Should Not Be Primary Join Keys)",
            "- blended derived keys are intentionally mixed into join columns",
            "- some joins require one-sided normalization and some both-sided normalization",
            "- shared low-cardinality columns: country, status, currency",
            "- date-like columns reused across tables",
            "- misleading names: cust_id / customer_key_id / customerId",
            "- overlapping region_code values (R01-R30) between customers and products",
        ]
    )

    (out_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    config = parse_args(argv)
    row_counts = generate_dataset(config)
    write_dataset_docs(config, row_counts)
    print(f"Generated dataset at: {config.out_dir.resolve()}")
    for table_name, count in row_counts.items():
        print(f"  - {table_name}: {count:,}")


if __name__ == "__main__":
    main()
