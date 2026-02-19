from pathlib import Path

import polars as pl

from alchemia.joins import find_join_candidates
from alchemia.models import Table


def test_find_join_candidates_detects_high_inclusion_foreign_key_pattern() -> None:
    customers = Table(
        name="customers",
        path=Path("customers.csv"),
        df=pl.DataFrame(
            {
                "customer_id": [1, 2, 3, 4],
                "name": ["a", "b", "c", "d"],
            }
        ),
    )
    orders = Table(
        name="orders",
        path=Path("orders.csv"),
        df=pl.DataFrame(
            {
                "order_id": [10, 11, 12, 13, 14],
                "customer_id": [2, 3, 4, 2, 3],
            }
        ),
    )

    candidates = find_join_candidates(
        tables=[customers, orders], sample_rows=10_000, min_confidence=0.8
    )

    match = next(
        c
        for c in candidates
        if c.left_column == "customer_id"
        and c.right_column == "customer_id"
        and c.left_table == "orders"
        and c.right_table == "customers"
    )
    assert match.confidence >= 0.8
    assert match.breakdown.signals["inclusion_fk_in_pk"] == 1.0
    assert match.breakdown.signals["inclusion_pk_in_fk"] == 0.75
    assert match.breakdown.signals["type_compatibility"] > 0.0


def test_find_join_candidates_filters_low_overlap() -> None:
    left = Table(
        name="left",
        path=Path("left.csv"),
        df=pl.DataFrame({"id": [1, 2, 3], "value": [100, 101, 102]}),
    )
    right = Table(
        name="right",
        path=Path("right.csv"),
        df=pl.DataFrame({"id": [9, 10, 11], "value": [200, 201, 202]}),
    )

    candidates = find_join_candidates(
        tables=[left, right],
        sample_rows=10_000,
        min_confidence=0.5,
    )
    assert candidates == []


def test_find_join_candidates_avoids_date_traps_with_shared_ranges() -> None:
    dim = Table(
        name="customers",
        path=Path("customers.csv"),
        df=pl.DataFrame(
            {
                "customer_id": [f"C{i:04d}" for i in range(1, 301)],
                "created_date": [f"2024-01-{(i % 28) + 1:02d}" for i in range(1, 301)],
            }
        ),
    )
    fact = Table(
        name="orders",
        path=Path("orders.csv"),
        df=pl.DataFrame(
            {
                "order_id": [f"O{i:05d}" for i in range(1, 601)],
                "created_date": [f"2024-01-{(i % 28) + 1:02d}" for i in range(1, 601)],
            }
        ),
    )

    candidates = find_join_candidates(tables=[dim, fact], sample_rows=500, min_confidence=0.5)
    date_joins = [
        c
        for c in candidates
        if c.left_column == "created_date" and c.right_column == "created_date"
    ]
    assert date_joins
    assert all(c.relationship_guess == "temporal_overlap" for c in date_joins)
    assert all(c.confidence <= 0.65 for c in date_joins)


def test_find_join_candidates_recovers_high_cardinality_id_subset() -> None:
    parent_ids = [f"O{i:07d}" for i in range(1, 50_001)]
    child_ids = [f"O{i:07d}" for i in range(10_001, 40_001)]

    parent = Table(
        name="orders",
        path=Path("orders.csv"),
        df=pl.DataFrame({"order_id": parent_ids}),
    )
    child = Table(
        name="payments",
        path=Path("payments.csv"),
        df=pl.DataFrame({"order_id": child_ids}),
    )

    candidates = find_join_candidates(
        tables=[parent, child],
        sample_rows=2_000,
        min_confidence=0.7,
    )
    match = next(
        c
        for c in candidates
        if c.left_table == "payments"
        and c.left_column == "order_id"
        and c.right_table == "orders"
        and c.right_column == "order_id"
    )
    assert match.confidence >= 0.7
    assert match.breakdown.signals["inclusion_fk_in_pk"] >= 0.7


def test_find_join_candidates_prefers_hub_table_for_shared_identifier_groups() -> None:
    orders = Table(
        name="orders",
        path=Path("orders.csv"),
        df=pl.DataFrame({"order_id": [f"O{i:05d}" for i in range(1, 201)]}),
    )
    payments = Table(
        name="payments",
        path=Path("payments.csv"),
        df=pl.DataFrame({"order_id": [f"O{i:05d}" for i in range(1, 161)]}),
    )
    shipments = Table(
        name="shipments",
        path=Path("shipments.csv"),
        df=pl.DataFrame({"order_id": [f"O{i:05d}" for i in range(1, 151)]}),
    )

    candidates = find_join_candidates(
        tables=[orders, payments, shipments],
        sample_rows=500,
        min_confidence=0.7,
    )
    edges = {
        (c.left_table, c.left_column, c.right_table, c.right_column)
        for c in candidates
        if c.left_column == "order_id" and c.right_column == "order_id"
    }

    assert ("payments", "order_id", "orders", "order_id") in edges
    assert ("shipments", "order_id", "orders", "order_id") in edges
    assert ("shipments", "order_id", "payments", "order_id") not in edges


def test_find_join_candidates_classifies_many_to_many() -> None:
    tags = Table(
        name="tags_a",
        path=Path("tags_a.csv"),
        df=pl.DataFrame({"tag_id": [1, 1, 2, 2, 3, 3]}),
    )
    events = Table(
        name="tags_b",
        path=Path("tags_b.csv"),
        df=pl.DataFrame({"tag_id": [1, 2, 2, 3, 3, 3]}),
    )

    candidates = find_join_candidates(tables=[tags, events], sample_rows=200, min_confidence=0.6)
    match = next(
        c
        for c in candidates
        if {c.left_table, c.right_table} == {"tags_a", "tags_b"}
        and c.left_column == "tag_id"
        and c.right_column == "tag_id"
    )
    assert match.relationship_guess == "many_to_many"


def test_find_join_candidates_classifies_bridge_to_dimension() -> None:
    orders = Table(
        name="orders",
        path=Path("orders.csv"),
        df=pl.DataFrame({"order_id": [1, 2, 3, 4]}),
    )
    products = Table(
        name="products",
        path=Path("products.csv"),
        df=pl.DataFrame({"product_id": [10, 11, 12]}),
    )
    bridge = Table(
        name="order_items",
        path=Path("order_items.csv"),
        df=pl.DataFrame(
            {
                "order_id": [1, 1, 2, 2, 3, 4],
                "product_id": [10, 11, 10, 12, 11, 10],
            }
        ),
    )

    candidates = find_join_candidates(
        tables=[orders, products, bridge],
        sample_rows=200,
        min_confidence=0.7,
    )
    order_join = next(
        c
        for c in candidates
        if c.left_table == "order_items"
        and c.left_column == "order_id"
        and c.right_table == "orders"
        and c.right_column == "order_id"
    )
    product_join = next(
        c
        for c in candidates
        if c.left_table == "order_items"
        and c.left_column == "product_id"
        and c.right_table == "products"
        and c.right_column == "product_id"
    )
    assert order_join.relationship_guess == "bridge_to_dimension"
    assert product_join.relationship_guess == "bridge_to_dimension"
