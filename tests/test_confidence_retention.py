from pathlib import Path

import polars as pl

from smartjoin.analysis import analyze_path
from smartjoin.models import AnalysisReport


def _edge_endpoints(
    left_table: str,
    left_column: str,
    right_table: str,
    right_column: str,
) -> tuple[str, str]:
    endpoints = [f"{left_table}.{left_column}", f"{right_table}.{right_column}"]
    endpoints.sort()
    return endpoints[0], endpoints[1]


def _write_confidence_fixture(path: Path) -> None:
    customer_count = 240
    order_count = 480
    customers = pl.DataFrame(
        {
            "customer_id": list(range(1, customer_count + 1)),
            "created_date": [
                f"2024-01-{((idx - 1) % 31) + 1:02d}" for idx in range(1, customer_count + 1)
            ],
            "status": ["active" if idx % 2 == 0 else "inactive" for idx in range(customer_count)],
        }
    )
    orders = pl.DataFrame(
        {
            "order_id": list(range(1, order_count + 1)),
            "customer_id": [((idx - 1) % customer_count) + 1 for idx in range(1, order_count + 1)],
            "created_date": [
                f"2024-01-{((idx - 1) % 31) + 1:02d}" for idx in range(1, order_count + 1)
            ],
        }
    )
    customers.write_csv(path / "customers.csv")
    orders.write_csv(path / "orders.csv")


def _visible_edges(report: AnalysisReport, threshold: float) -> set[tuple[str, str]]:
    joins = [join for join in report.joins if join.confidence >= threshold]
    return {
        _edge_endpoints(join.left_table, join.left_column, join.right_table, join.right_column)
        for join in joins
    }


def test_analysis_keeps_lower_confidence_candidates_for_internal_retention(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_confidence_fixture(data_dir)

    report = analyze_path(
        path=data_dir,
        sample_rows=5_000,
        min_confidence=0.8,
    )

    low_confidence = [
        join for join in report.joins if join.confidence < report.settings.min_confidence
    ]
    assert low_confidence
    assert any(
        _edge_endpoints(join.left_table, join.left_column, join.right_table, join.right_column)
        == ("customers.created_date", "orders.created_date")
        for join in low_confidence
    )
    visible_edges = _visible_edges(report, report.settings.min_confidence)
    assert ("customers.created_date", "orders.created_date") not in visible_edges


def test_lowering_visible_threshold_exposes_more_edges_without_rerunning_discovery(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_confidence_fixture(data_dir)

    report = analyze_path(
        path=data_dir,
        sample_rows=5_000,
        min_confidence=0.8,
    )
    high_edges = _visible_edges(report, 0.8)
    low_edges = _visible_edges(report, 0.6)

    assert high_edges.issubset(low_edges)
    assert len(low_edges) > len(high_edges)
    assert ("customers.created_date", "orders.created_date") not in high_edges
    assert ("customers.created_date", "orders.created_date") in low_edges
