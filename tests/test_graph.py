from pathlib import Path

import polars as pl

from alchemia.graphing import build_join_graph, graph_to_report
from alchemia.joins import find_join_candidates
from alchemia.models import JoinCandidate, JoinScoreBreakdown, Table


def test_build_join_graph_returns_nodes_and_edges() -> None:
    customers = Table(
        name="customers",
        path=Path("customers.csv"),
        df=pl.DataFrame({"customer_id": [1, 2, 3]}),
    )
    orders = Table(
        name="orders",
        path=Path("orders.csv"),
        df=pl.DataFrame({"order_id": [10, 11, 12], "customer_id": [1, 2, 2]}),
    )
    joins = find_join_candidates([customers, orders], min_confidence=0.6)
    graph = build_join_graph([customers, orders], joins, min_confidence=0.6)
    report = graph_to_report(graph)

    assert len(report.nodes) == 2
    assert len(report.edges) >= 1
    assert all(edge.edge_group_id for edge in report.edges)
    assert all(edge.edge_rank >= 1 for edge in report.edges)


def test_build_join_graph_keeps_top_k_alternatives_per_pair() -> None:
    customers = Table(
        name="customers",
        path=Path("customers.csv"),
        df=pl.DataFrame({"customer_id": [1, 2, 3]}),
    )
    orders = Table(
        name="orders",
        path=Path("orders.csv"),
        df=pl.DataFrame({"order_id": [10, 11, 12], "customer_id": [1, 2, 2]}),
    )

    def candidate(left_col: str, confidence: float) -> JoinCandidate:
        return JoinCandidate(
            left_table="orders",
            left_column=left_col,
            right_table="customers",
            right_column="customer_id",
            confidence=confidence,
            relationship_guess="many_to_one",
            breakdown=JoinScoreBreakdown(
                signals={"inclusion_fk_in_pk": 1.0},
                weights={"inclusion_fk_in_pk": 1.0},
                weighted_score=confidence,
            ),
        )

    joins = [
        candidate("customer_id", 0.95),
        candidate("order_id", 0.90),
        candidate("status_id", 0.85),
    ]
    graph = build_join_graph(
        tables=[customers, orders],
        joins=joins,
        min_confidence=0.0,
        top_k_per_pair=2,
    )
    report = graph_to_report(graph)

    assert len(report.edges) == 2
    assert len({edge.edge_group_id for edge in report.edges}) == 1
    assert sorted(edge.edge_rank for edge in report.edges) == [1, 2]
