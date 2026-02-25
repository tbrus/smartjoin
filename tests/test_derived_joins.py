from datetime import date, timedelta
from pathlib import Path

import polars as pl

from smartjoin.joins import find_join_candidates
from smartjoin.models import Table


def test_derived_key_join_matches_parent_key_and_rejects_incompatible_namespace() -> None:
    products = Table(
        name="products",
        path=Path("products.csv"),
        df=pl.DataFrame(
            {
                "product_key": ["prod-00123", "prod-00456", "prod-00789", "prod-00123"],
            }
        ),
    )
    product_dim = Table(
        name="product_dim",
        path=Path("product_dim.csv"),
        df=pl.DataFrame(
            {
                "product_id": ["prd00123", "prd00456", "prd00789"],
            }
        ),
    )
    customers = Table(
        name="customers",
        path=Path("customers.csv"),
        df=pl.DataFrame(
            {
                "customer_id": ["cust-00123", "cust-00456", "cust-00789"],
            }
        ),
    )

    candidates = find_join_candidates(
        tables=[products, product_dim, customers],
        sample_rows=100,
        min_confidence=0.75,
        derived_min_distinct=2,
    )

    product_join = next(
        c
        for c in candidates
        if c.left_table == "products"
        and c.left_column == "product_key"
        and c.right_table == "product_dim"
        and c.right_column == "product_id"
    )
    assert product_join.derived is not None
    assert product_join.derived.transform_id == "replace_prefix"
    assert product_join.derived.derived_from_table == "products"
    assert product_join.derived.derived_from_column == "product_key"
    assert product_join.confidence >= 0.75

    blocked_edges = [
        c
        for c in candidates
        if {f"{c.left_table}.{c.left_column}", f"{c.right_table}.{c.right_column}"}
        == {"products.product_key", "customers.customer_id"}
    ]
    assert blocked_edges == []


def test_date_like_columns_never_use_derived_transforms() -> None:
    calendar = Table(
        name="calendar",
        path=Path("calendar.csv"),
        df=pl.DataFrame(
            {
                "calendar_date": [f"2025-01-{day:02d}" for day in range(1, 31)],
            }
        ),
    )
    orders = Table(
        name="orders",
        path=Path("orders.csv"),
        df=pl.DataFrame(
            {
                "order_date": [f"2025-01-{((i - 1) % 30) + 1:02d}" for i in range(1, 91)],
            }
        ),
    )

    candidates = find_join_candidates(
        tables=[calendar, orders],
        sample_rows=200,
        min_confidence=0.5,
        derived_min_distinct=2,
    )

    date_joins = [
        c
        for c in candidates
        if {f"{c.left_table}.{c.left_column}", f"{c.right_table}.{c.right_column}"}
        == {"calendar.calendar_date", "orders.order_date"}
    ]
    assert date_joins
    assert all(c.derived is None for c in date_joins)


def test_derived_join_handles_string_to_numeric_targets() -> None:
    ledger_events = Table(
        name="ledger_events",
        path=Path("ledger_events.csv"),
        df=pl.DataFrame(
            {
                "payment_key": [
                    "pay-00001",
                    "pay_00002",
                    "PAY00003",
                    "pay-00004",
                    "pay-00001",
                ],
            }
        ),
    )
    payment_dim = Table(
        name="payment_dim",
        path=Path("payment_dim.csv"),
        df=pl.DataFrame(
            {
                "payment_id": [1, 2, 3, 4],
            }
        ),
    )
    refund_dim = Table(
        name="refund_dim",
        path=Path("refund_dim.csv"),
        df=pl.DataFrame(
            {
                "refund_id": [1, 2, 3, 4],
            }
        ),
    )

    candidates = find_join_candidates(
        tables=[ledger_events, payment_dim, refund_dim],
        sample_rows=200,
        min_confidence=0.75,
        derived_min_distinct=2,
    )

    payment_join = next(
        c
        for c in candidates
        if c.left_table == "ledger_events"
        and c.left_column == "payment_key"
        and c.right_table == "payment_dim"
        and c.right_column == "payment_id"
    )
    assert payment_join.derived is not None
    assert payment_join.derived.transform_id == "remove_prefix"
    assert payment_join.confidence >= 0.75

    blocked_refund_edges = [
        c
        for c in candidates
        if {f"{c.left_table}.{c.left_column}", f"{c.right_table}.{c.right_column}"}
        == {"ledger_events.payment_key", "refund_dim.refund_id"}
    ]
    assert blocked_refund_edges == []


def test_direct_identifier_namespace_collision_is_rejected() -> None:
    payment_dim = Table(
        name="payment_dim",
        path=Path("payment_dim.csv"),
        df=pl.DataFrame(
            {
                "payment_id": [1, 2, 3, 4, 5],
            }
        ),
    )
    refund_dim = Table(
        name="refund_dim",
        path=Path("refund_dim.csv"),
        df=pl.DataFrame(
            {
                "refund_id": [1, 2, 3, 4, 5],
            }
        ),
    )

    candidates = find_join_candidates(
        tables=[payment_dim, refund_dim],
        sample_rows=200,
        min_confidence=0.75,
        derived_min_distinct=2,
    )

    blocked_edges = [
        c
        for c in candidates
        if {f"{c.left_table}.{c.left_column}", f"{c.right_table}.{c.right_column}"}
        == {"payment_dim.payment_id", "refund_dim.refund_id"}
    ]
    assert blocked_edges == []


def test_temporal_equivalent_targets_prefer_plain_date_column() -> None:
    calendar_dates = [
        (date(2025, 1, 1) + timedelta(days=offset)).isoformat() for offset in range(40)
    ]
    event_dates = [calendar_dates[idx % len(calendar_dates)] for idx in range(160)]
    orders = Table(
        name="order_events",
        path=Path("order_events.csv"),
        df=pl.DataFrame(
            {
                "order_date": event_dates,
            }
        ),
    )
    calendar = Table(
        name="calendar_dim",
        path=Path("calendar_dim.csv"),
        df=pl.DataFrame(
            {
                "calendar_date": calendar_dates,
                "calendar_date_id": calendar_dates,
            }
        ),
    )

    candidates = find_join_candidates(
        tables=[orders, calendar],
        sample_rows=200,
        min_confidence=0.75,
        derived_min_distinct=2,
    )
    edge_strings = {
        f"{c.left_table}.{c.left_column}->{c.right_table}.{c.right_column}" for c in candidates
    }
    assert "order_events.order_date->calendar_dim.calendar_date" in edge_strings
    assert "order_events.order_date->calendar_dim.calendar_date_id" not in edge_strings


def test_date_key_to_date_id_join_is_preserved() -> None:
    fact = Table(
        name="fact_orders",
        path=Path("fact_orders.csv"),
        df=pl.DataFrame(
            {
                "date_key": [20250101, 20250102, 20250101, 20250103, 20250102],
            }
        ),
    )
    date_dim = Table(
        name="date_dim",
        path=Path("date_dim.csv"),
        df=pl.DataFrame(
            {
                "date_id": [20250101, 20250102, 20250103],
                "calendar_date": ["2025-01-01", "2025-01-02", "2025-01-03"],
            }
        ),
    )

    candidates = find_join_candidates(
        tables=[fact, date_dim],
        sample_rows=200,
        min_confidence=0.75,
        derived_min_distinct=2,
    )
    key_joins = [
        c
        for c in candidates
        if c.left_table == "fact_orders"
        and c.left_column == "date_key"
        and c.right_table == "date_dim"
        and c.right_column == "date_id"
    ]
    assert key_joins


def test_noncanonical_alias_edge_is_suppressed_when_canonical_exists() -> None:
    accounts = Table(
        name="accounts",
        path=Path("accounts.csv"),
        df=pl.DataFrame(
            {
                "account_id": [f"ACC{i:06d}" for i in range(1, 121)],
                "acct_id": [
                    f"ACC{i:06d}" if i % 7 else f"ACT{i:06d}"
                    for i in range(1, 121)
                ],
            }
        ),
    )
    workspaces = Table(
        name="workspaces",
        path=Path("workspaces.csv"),
        df=pl.DataFrame(
            {
                "account_key_id": [f"ACC{((i - 1) % 120) + 1:06d}" for i in range(1, 481)],
            }
        ),
    )

    candidates = find_join_candidates(
        tables=[accounts, workspaces],
        sample_rows=1000,
        min_confidence=0.72,
        derived_min_distinct=20,
    )
    edge_strings = {
        f"{c.left_table}.{c.left_column}<->{c.right_table}.{c.right_column}" for c in candidates
    }
    canonical_present = any(
        {f"{c.left_table}.{c.left_column}", f"{c.right_table}.{c.right_column}"}
        == {"workspaces.account_key_id", "accounts.account_id"}
        for c in candidates
    )
    alias_present = any(
        {f"{c.left_table}.{c.left_column}", f"{c.right_table}.{c.right_column}"}
        == {"workspaces.account_key_id", "accounts.acct_id"}
        for c in candidates
    )
    assert canonical_present, edge_strings
    assert not alias_present, edge_strings


def test_direct_join_outranks_similar_derived_join() -> None:
    item_dim = Table(
        name="item_dim",
        path=Path("item_dim.csv"),
        df=pl.DataFrame(
            {
                "id": [f"x{i:05d}" for i in range(1, 121)],
            }
        ),
    )
    direct_events = Table(
        name="direct_events",
        path=Path("direct_events.csv"),
        df=pl.DataFrame(
            {
                "id": [f"x{((i - 1) % 120) + 1:05d}" for i in range(1, 481)],
            }
        ),
    )
    derived_events = Table(
        name="derived_events",
        path=Path("derived_events.csv"),
        df=pl.DataFrame(
            {
                "id": [f"x#{((i - 1) % 120) + 1:05d}" for i in range(1, 481)],
            }
        ),
    )

    candidates = find_join_candidates(
        tables=[item_dim, direct_events, derived_events],
        sample_rows=2_000,
        min_confidence=0.7,
        derived_min_distinct=20,
    )

    direct_join = next(
        c
        for c in candidates
        if {f"{c.left_table}.{c.left_column}", f"{c.right_table}.{c.right_column}"}
        == {"direct_events.id", "item_dim.id"}
    )
    derived_join = next(
        c
        for c in candidates
        if {f"{c.left_table}.{c.left_column}", f"{c.right_table}.{c.right_column}"}
        == {"derived_events.id", "item_dim.id"}
    )

    assert direct_join.derived is None
    assert derived_join.derived is not None
    assert direct_join.breakdown.signals["inclusion_fk_in_pk"] >= 0.99
    assert derived_join.breakdown.signals["inclusion_fk_in_pk"] >= 0.99
    assert direct_join.confidence > derived_join.confidence
