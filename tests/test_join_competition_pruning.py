from pathlib import Path

import polars as pl

from smartjoin.joins import find_join_candidates
from smartjoin.models import Table


def test_competing_one_to_many_targets_keep_strongest() -> None:
    products = Table(
        name="products",
        path=Path("products.csv"),
        df=pl.DataFrame(
            {
                "product_id": [f"P{i:03d}" for i in range(1, 51)],
                "product_code": [f"P{i:03d}" for i in range(1, 51)],
                "sku": [f"SKU{i:03d}" for i in range(1, 51)],
            }
        ),
    )
    order_items = Table(
        name="order_items",
        path=Path("order_items.csv"),
        df=pl.DataFrame(
            {
                "product_id": [f"P{((i - 1) % 50) + 1:03d}" for i in range(1, 201)],
                "quantity": [1 + (i % 3) for i in range(1, 201)],
            }
        ),
    )

    candidates = find_join_candidates(
        tables=[products, order_items],
        sample_rows=1_000,
        min_confidence=0.5,
    )
    competing = [
        candidate
        for candidate in candidates
        if candidate.left_table == "order_items"
        and candidate.left_column == "product_id"
        and candidate.right_table == "products"
        and candidate.right_column in {"product_id", "product_code"}
    ]
    assert len(competing) == 1
    assert competing[0].right_column == "product_id"


def test_competing_many_to_many_duplicates_are_pruned() -> None:
    tags_a = Table(
        name="tags_a",
        path=Path("tags_a.csv"),
        df=pl.DataFrame(
            {
                "tag_id": [1, 1, 2, 2, 3, 3, 4, 4, 5, 5],
                "event_code": [f"E{i}" for i in range(1, 11)],
            }
        ),
    )
    tags_b = Table(
        name="tags_b",
        path=Path("tags_b.csv"),
        df=pl.DataFrame(
            {
                "tag_id": [1, 2, 2, 3, 3, 4, 4, 5, 5, 5],
                "tag_code": [1, 2, 2, 3, 3, 4, 4, 5, 5, 5],
                "label": ["a", "b", "b", "c", "c", "d", "d", "e", "e", "e"],
            }
        ),
    )

    candidates = find_join_candidates(
        tables=[tags_a, tags_b],
        sample_rows=500,
        min_confidence=0.5,
    )
    competing = [
        candidate
        for candidate in candidates
        if candidate.left_table == "tags_a"
        and candidate.left_column == "tag_id"
        and candidate.right_table == "tags_b"
        and candidate.right_column in {"tag_id", "tag_code"}
    ]
    assert len(competing) == 1
    assert competing[0].right_column == "tag_id"
    assert competing[0].relationship_guess == "many_to_many"


def test_distinct_multi_join_relationships_are_preserved() -> None:
    users = Table(
        name="users",
        path=Path("users.csv"),
        df=pl.DataFrame(
            {
                "user_id": [f"U{i:03d}" for i in range(1, 81)],
                "email": [f"u{i}@example.com" for i in range(1, 81)],
            }
        ),
    )
    orders = Table(
        name="orders",
        path=Path("orders.csv"),
        df=pl.DataFrame(
            {
                "order_id": [f"O{i:04d}" for i in range(1, 201)],
                "buyer_id": [f"U{((i - 1) % 80) + 1:03d}" for i in range(1, 201)],
                "seller_id": [f"U{((i + 19) % 80) + 1:03d}" for i in range(1, 201)],
            }
        ),
    )

    candidates = find_join_candidates(
        tables=[users, orders],
        sample_rows=1_000,
        min_confidence=0.6,
    )
    buyer_join = any(
        candidate.left_table == "orders"
        and candidate.left_column == "buyer_id"
        and candidate.right_table == "users"
        and candidate.right_column == "user_id"
        for candidate in candidates
    )
    seller_join = any(
        candidate.left_table == "orders"
        and candidate.left_column == "seller_id"
        and candidate.right_table == "users"
        and candidate.right_column == "user_id"
        for candidate in candidates
    )

    assert buyer_join
    assert seller_join


def test_competing_transform_variants_to_same_target_are_pruned() -> None:
    item_ids = [f"X{i:05d}" for i in range(1, 81)]
    dim = Table(
        name="items_dim",
        path=Path("items_dim.csv"),
        df=pl.DataFrame(
            {
                "item_id": item_ids,
            }
        ),
    )
    events = Table(
        name="items_events",
        path=Path("items_events.csv"),
        df=pl.DataFrame(
            {
                "direct_item_id": [item_ids[(i - 1) % 80] for i in range(1, 321)],
                "item_key_dash": [f"X-{((i - 1) % 80) + 1:05d}" for i in range(1, 321)],
                "item_key_under": [f"X_{((i - 1) % 80) + 1:05d}" for i in range(1, 321)],
                "item_key_slash": [f"X/{((i - 1) % 80) + 1:05d}" for i in range(1, 321)],
                "item_key_hash": [f"X#{((i - 1) % 80) + 1:05d}" for i in range(1, 321)],
                "event_id": [f"EV{i:06d}" for i in range(1, 321)],
            }
        ),
    )

    candidates = find_join_candidates(
        tables=[dim, events],
        sample_rows=2_000,
        min_confidence=0.7,
    )
    to_item_id = [
        candidate
        for candidate in candidates
        if candidate.left_table == "items_events"
        and candidate.right_table == "items_dim"
        and candidate.right_column == "item_id"
        and candidate.left_column
        in {
            "direct_item_id",
            "item_key_dash",
            "item_key_under",
            "item_key_slash",
            "item_key_hash",
        }
    ]
    assert len(to_item_id) == 1
    assert to_item_id[0].left_column == "direct_item_id"


def test_competing_alias_source_columns_to_same_target_are_pruned() -> None:
    customers = Table(
        name="customers",
        path=Path("customers.csv"),
        df=pl.DataFrame(
            {
                "customer_id": [f"C{i:04d}" for i in range(1, 101)],
                "segment": ["smb" if i % 2 == 0 else "ent" for i in range(1, 101)],
            }
        ),
    )
    orders = Table(
        name="orders",
        path=Path("orders.csv"),
        df=pl.DataFrame(
            {
                "order_id": [f"O{i:06d}" for i in range(1, 401)],
                "customer_id": [f"C{((i - 1) % 100) + 1:04d}" for i in range(1, 401)],
                "customer_alt_id": [f"C{((i - 1) % 100) + 1:04d}" for i in range(1, 401)],
            }
        ),
    )

    candidates = find_join_candidates(
        tables=[customers, orders],
        sample_rows=2_000,
        min_confidence=0.7,
    )
    to_customer_id = [
        candidate
        for candidate in candidates
        if candidate.left_table == "orders"
        and candidate.right_table == "customers"
        and candidate.right_column == "customer_id"
        and candidate.left_column in {"customer_id", "customer_alt_id"}
    ]
    assert len(to_customer_id) == 1
    assert to_customer_id[0].left_column == "customer_id"


def test_semantically_distinct_same_table_pair_joins_are_preserved() -> None:
    reference = Table(
        name="reference",
        path=Path("reference.csv"),
        df=pl.DataFrame(
            {
                "country_code": [f"CTY{i:03d}" for i in range(1, 81)],
                "currency_code": [f"CUR{i:03d}" for i in range(1, 81)],
                "label": [f"label-{i}" for i in range(1, 81)],
            }
        ),
    )
    invoices = Table(
        name="invoices",
        path=Path("invoices.csv"),
        df=pl.DataFrame(
            {
                "invoice_id": [f"I{i:06d}" for i in range(1, 321)],
                "country_code": [f"CTY{((i - 1) % 80) + 1:03d}" for i in range(1, 321)],
                "currency_code": [f"CUR{((i - 1) % 80) + 1:03d}" for i in range(1, 321)],
            }
        ),
    )

    candidates = find_join_candidates(
        tables=[reference, invoices],
        sample_rows=2_000,
        min_confidence=0.65,
    )
    country_join = any(
        candidate.left_table == "invoices"
        and candidate.left_column == "country_code"
        and candidate.right_table == "reference"
        and candidate.right_column == "country_code"
        for candidate in candidates
    )
    currency_join = any(
        candidate.left_table == "invoices"
        and candidate.left_column == "currency_code"
        and candidate.right_table == "reference"
        and candidate.right_column == "currency_code"
        for candidate in candidates
    )
    assert country_join
    assert currency_join
