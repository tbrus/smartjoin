from pathlib import Path

import polars as pl

from alchemia.joins import build_column_signatures
from alchemia.models import Table


def test_build_column_signatures_is_deterministic_for_same_seed() -> None:
    table = Table(
        name="events",
        path=Path("events.csv"),
        df=pl.DataFrame({"id": list(range(1, 101))}),
    )

    first = build_column_signatures([table], sample_rows=12, sample_seed=42)
    second = build_column_signatures([table], sample_rows=12, sample_seed=42)

    assert first[("events", "id")].sampled_unique_set == second[("events", "id")].sampled_unique_set


def test_build_column_signatures_changes_sample_with_different_seed() -> None:
    table = Table(
        name="events",
        path=Path("events.csv"),
        df=pl.DataFrame({"id": list(range(1, 101))}),
    )

    first = build_column_signatures([table], sample_rows=12, sample_seed=1)
    second = build_column_signatures([table], sample_rows=12, sample_seed=2)

    assert first[("events", "id")].sampled_unique_set != second[("events", "id")].sampled_unique_set
