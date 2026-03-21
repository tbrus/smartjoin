from pathlib import Path

import polars as pl

from smartjoin.keys import discover_keys
from smartjoin.models import Table


def test_discover_keys_finds_primary_and_composite_candidates() -> None:
    customers = Table(
        name="customers",
        path=Path("customers.csv"),
        df=pl.DataFrame({"customer_id": [1, 2, 3], "name": ["a", "b", "c"]}),
    )
    order_items = Table(
        name="order_items",
        path=Path("order_items.csv"),
        df=pl.DataFrame(
            {
                "order_id": [10, 10, 11, 11],
                "line_no": [1, 2, 1, 2],
                "sku": ["x", "y", "x", "z"],
            }
        ),
    )

    results = discover_keys([customers, order_items], max_combinations=20)
    by_table = {item.table_name: item for item in results}

    assert by_table["customers"].primary_key_candidates
    assert by_table["customers"].primary_key_candidates[0].columns == ["customer_id"]
    assert any(
        candidate.columns == ["order_id", "line_no"]
        for candidate in by_table["order_items"].composite_key_candidates
    )
