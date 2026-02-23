"""Typed models for analysis outputs and in-memory tables."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import polars as pl
from pydantic import BaseModel, Field


@dataclass(frozen=True)
class Table:
    """Standard internal table object used by analysis modules."""

    name: str
    df: pl.DataFrame
    path: Path
    metadata: dict[str, Any] = field(default_factory=dict)


class ColumnProfile(BaseModel):
    """Per-column profiling statistics."""

    name: str
    dtype: str
    null_pct: float = Field(ge=0.0, le=1.0)
    distinct_count: int = Field(ge=0)
    unique_ratio: float = Field(ge=0.0, le=1.0)
    near_unique: bool = False
    entropy: float = Field(ge=0.0)
    sample_values: list[Any]
    min_value: Any = None
    max_value: Any = None
    avg_length: float | None = Field(default=None, ge=0.0)
    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=0)


class TableProfile(BaseModel):
    """Per-table profile output."""

    table_name: str
    row_count: int = Field(ge=0)
    duplicate_row_count: int = Field(ge=0)
    duplicate_row_pct: float = Field(ge=0.0, le=1.0)
    candidate_unique_columns: list[str]
    near_unique_columns: list[str]
    columns: list[ColumnProfile]


class KeyCandidate(BaseModel):
    """Candidate key with supporting metrics."""

    table_name: str
    columns: list[str]
    uniqueness_ratio: float = Field(ge=0.0, le=1.0)
    null_row_pct: float = Field(ge=0.0, le=1.0)
    score: float = Field(ge=0.0, le=1.0)
    rationale: str


class TableKeyDiscovery(BaseModel):
    """Key discovery output per table."""

    table_name: str
    primary_key_candidates: list[KeyCandidate]
    composite_key_candidates: list[KeyCandidate]


class JoinScoreBreakdown(BaseModel):
    """Signal-level details for explainable join confidence."""

    signals: dict[str, float]
    weights: dict[str, float]
    weighted_score: float = Field(ge=0.0, le=1.0)


class JoinCandidate(BaseModel):
    """Join edge candidate between two columns."""

    left_table: str
    left_column: str
    right_table: str
    right_column: str
    confidence: float = Field(ge=0.0, le=1.0)
    relationship_guess: str
    breakdown: JoinScoreBreakdown


class JoinGraphNode(BaseModel):
    """Join graph node."""

    table_name: str
    row_count: int = Field(ge=0)


class JoinGraphEdge(BaseModel):
    """Join graph edge."""

    left_table: str
    right_table: str
    left_column: str
    right_column: str
    edge_group_id: str
    edge_rank: int = Field(ge=1)
    confidence: float = Field(ge=0.0, le=1.0)
    relationship_guess: str


class JoinGraphReport(BaseModel):
    """Serializable join graph report."""

    top_k_per_pair: int = Field(ge=1)
    min_confidence: float = Field(ge=0.0, le=1.0)
    nodes: list[JoinGraphNode]
    edges: list[JoinGraphEdge]


class AnalysisSettingsReport(BaseModel):
    """Settings snapshot used to generate a report."""

    min_confidence: float = Field(ge=0.0, le=1.0)
    top_k_edges: int = Field(ge=1)
    sample_rows: int = Field(ge=1)
    sample_seed: int = Field(ge=0)
    distinct_low_card_threshold: int = Field(ge=1)
    near_unique_threshold: float = Field(ge=0.0, le=1.0)
    date_caps: dict[str, float]


class AnalysisReport(BaseModel):
    """Top-level JSON report produced by `smartjoin analyze`."""

    source_path: str
    settings: AnalysisSettingsReport
    tables: list[TableProfile]
    keys: list[TableKeyDiscovery]
    joins: list[JoinCandidate]
    graph: JoinGraphReport
