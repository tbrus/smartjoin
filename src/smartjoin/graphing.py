"""Join graph construction and serialization."""

from __future__ import annotations

from collections import defaultdict

import networkx as nx

from smartjoin.models import JoinCandidate, JoinGraphEdge, JoinGraphNode, JoinGraphReport, Table


def _edge_group_id(left_table: str, right_table: str) -> str:
    left, right = sorted([left_table, right_table])
    return f"{left}::{right}"


def build_join_graph(
    tables: list[Table],
    joins: list[JoinCandidate],
    min_confidence: float = 0.8,
    top_k_per_pair: int = 3,
) -> nx.MultiGraph:
    """Build a graph of table joins above threshold, retaining top-K alternatives per pair."""
    graph = nx.MultiGraph()
    effective_top_k = max(1, top_k_per_pair)
    graph.graph["top_k_per_pair"] = int(effective_top_k)
    graph.graph["min_confidence"] = float(min_confidence)

    for table in tables:
        graph.add_node(table.name, row_count=table.df.height)

    grouped: dict[str, list[JoinCandidate]] = defaultdict(list)
    for join in joins:
        if join.confidence < min_confidence:
            continue
        grouped[_edge_group_id(join.left_table, join.right_table)].append(join)

    for edge_group_id, candidates in grouped.items():
        ranked = sorted(
            candidates,
            key=lambda join: (
                -join.confidence,
                join.left_table.lower(),
                join.left_column.lower(),
                join.right_table.lower(),
                join.right_column.lower(),
            ),
        )
        for rank, join in enumerate(ranked[:effective_top_k], start=1):
            graph.add_edge(
                join.left_table,
                join.right_table,
                left_column=join.left_column,
                right_column=join.right_column,
                edge_group_id=edge_group_id,
                edge_rank=rank,
                confidence=join.confidence,
                relationship_guess=join.relationship_guess,
                derived=join.derived.model_dump(mode="json") if join.derived is not None else None,
            )

    return graph


def graph_to_report(
    graph: nx.Graph | nx.MultiGraph,
    top_k_per_pair: int | None = None,
    min_confidence: float | None = None,
) -> JoinGraphReport:
    """Convert NetworkX graph into typed report model."""
    resolved_top_k = int(top_k_per_pair or graph.graph.get("top_k_per_pair", 1))
    resolved_min_confidence = float(
        min_confidence if min_confidence is not None else graph.graph.get("min_confidence", 0.0)
    )
    nodes = [
        JoinGraphNode(
            table_name=str(node_name),
            row_count=int(attributes.get("row_count", 0)),
        )
        for node_name, attributes in graph.nodes(data=True)
    ]
    nodes = sorted(nodes, key=lambda node: node.table_name.lower())

    edges = []
    if graph.is_multigraph():
        edge_iter = graph.edges(keys=True, data=True)
        for left_table, right_table, _edge_key, attributes in edge_iter:
                edge = JoinGraphEdge(
                    left_table=str(left_table),
                    right_table=str(right_table),
                    left_column=str(attributes.get("left_column", "")),
                    right_column=str(attributes.get("right_column", "")),
                edge_group_id=str(
                    attributes.get(
                        "edge_group_id",
                        _edge_group_id(str(left_table), str(right_table)),
                    )
                    ),
                    edge_rank=int(attributes.get("edge_rank", 1)),
                    confidence=float(attributes.get("confidence", 0.0)),
                    relationship_guess=str(attributes.get("relationship_guess", "unknown")),
                    derived=attributes.get("derived"),
                )
                edges.append(edge)
    else:
        for left_table, right_table, attributes in graph.edges(data=True):
            edge = JoinGraphEdge(
                left_table=str(left_table),
                right_table=str(right_table),
                left_column=str(attributes.get("left_column", "")),
                right_column=str(attributes.get("right_column", "")),
                edge_group_id=str(
                    attributes.get(
                        "edge_group_id",
                        _edge_group_id(str(left_table), str(right_table)),
                    )
                ),
                edge_rank=int(attributes.get("edge_rank", 1)),
                confidence=float(attributes.get("confidence", 0.0)),
                relationship_guess=str(attributes.get("relationship_guess", "unknown")),
                derived=attributes.get("derived"),
            )
            edges.append(edge)
    edges = sorted(
        edges,
        key=lambda edge: (
            -edge.confidence,
            edge.edge_group_id,
            edge.edge_rank,
            edge.left_table.lower(),
            edge.right_table.lower(),
            edge.left_column.lower(),
            edge.right_column.lower(),
        ),
    )

    return JoinGraphReport(
        top_k_per_pair=max(1, resolved_top_k),
        min_confidence=max(0.0, min(1.0, resolved_min_confidence)),
        nodes=nodes,
        edges=edges,
    )
