"""Column signature cache for join discovery."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

import polars as pl

from smartjoin.models import Table


@dataclass(frozen=True)
class NameFeatures:
    """Normalized name features used by join heuristics."""

    normalized: str
    tokens: tuple[str, ...]
    id_like: bool
    key_like: bool
    code_like: bool
    identifier_like: bool
    entity_core: str
    date_like: bool


@dataclass(frozen=True)
class ColumnSignature:
    """Cached column signature for fast join candidate scoring."""

    table_name: str
    column_name: str
    dtype: pl.DataType
    sampled_unique_set: frozenset[object]
    sampled_distinct_count: int
    distinct_count: int
    uniqueness_ratio: float
    non_null_count: int
    row_count: int
    name_features: NameFeatures


SignatureKey = tuple[str, str]
SignatureCache = dict[SignatureKey, ColumnSignature]


def _stable_seed(sample_seed: int, table_name: str, column_name: str) -> int:
    payload = f"{sample_seed}|{table_name}|{column_name}".encode()
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], byteorder="little", signed=False)


def _to_hashable(value: Any) -> object:
    if isinstance(value, (dict, list, tuple, set)):
        try:
            return json.dumps(value, sort_keys=True, default=str)
        except TypeError:
            return str(value)
    if isinstance(value, (str, int, float, bool, bytes, type(None))):
        return value
    return str(value)


def _normalize_value(value: Any, name_features: NameFeatures) -> object:
    """Normalize values for deterministic and robust set-based comparisons."""
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return ""

        if name_features.identifier_like or name_features.code_like:
            cleaned_upper = cleaned.upper()
            match = re.fullmatch(r"0*([A-Z]+)[_\-\s]*0*([0-9]+)", cleaned_upper)
            if match:
                prefix, digits = match.groups()
                return f"{prefix}{int(digits)}"

            numeric = re.fullmatch(r"0*([0-9]+)", cleaned_upper)
            if numeric:
                return str(int(numeric.group(1)))
            return cleaned_upper

        return cleaned

    return _to_hashable(value)


def _build_name_features(column_name: str) -> NameFeatures:
    with_snake = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", column_name)
    tokens = tuple(token for token in with_snake.lower().split("_") if token)
    normalized = "".join(tokens)
    id_like = normalized.endswith("id") or "id" in tokens or "uuid" in tokens
    key_like = "key" in tokens or "ref" in tokens
    code_like = "code" in tokens
    identifier_like = id_like or key_like
    qualifier_tokens = {
        "id",
        "key",
        "ref",
        "code",
        "uuid",
        "alt",
        "legacy",
        "old",
        "new",
        "primary",
        "secondary",
    }

    def _normalize_entity_token(token: str) -> str:
        # Generic token normalization for singular/plural variants.
        normalized_token = token.lower()
        if normalized_token.endswith("ies") and len(normalized_token) > 3:
            return normalized_token[:-3] + "y"
        if normalized_token.endswith("s") and len(normalized_token) > 3:
            return normalized_token[:-1]
        return normalized_token

    entity_core = "".join(
        _normalize_entity_token(token)
        for token in tokens
        if token not in qualifier_tokens
    )
    date_tokens = {
        "date",
        "time",
        "timestamp",
        "created",
        "updated",
        "shipped",
        "delivered",
        "start",
        "end",
        "applied",
    }
    date_like = any(token in date_tokens for token in tokens)
    return NameFeatures(
        normalized=normalized,
        tokens=tokens,
        id_like=id_like,
        key_like=key_like,
        code_like=code_like,
        identifier_like=identifier_like,
        entity_core=entity_core,
        date_like=date_like,
    )


def _sampled_unique_values(
    series: pl.Series,
    table_name: str,
    column_name: str,
    name_features: NameFeatures,
    sample_rows: int,
    sample_seed: int,
    sampled_unique_cap: int,
) -> frozenset[object]:
    if series.len() == 0:
        return frozenset()

    distinct = series.drop_nulls().unique(maintain_order=False)
    if distinct.len() == 0:
        return frozenset()

    n = min(sample_rows, distinct.len())
    seed = _stable_seed(sample_seed=sample_seed, table_name=table_name, column_name=column_name)
    sampled = distinct.sample(
        n=n,
        with_replacement=False,
        shuffle=True,
        seed=seed,
    )
    unique_values = sampled.to_list()

    out: list[object] = []
    seen: set[object] = set()
    for value in unique_values:
        normalized = _normalize_value(value, name_features=name_features)
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
        if len(out) >= sampled_unique_cap:
            break
    return frozenset(out)


def build_column_signatures(
    tables: list[Table],
    sample_rows: int = 10_000,
    sample_seed: int = 42,
    sampled_unique_cap: int = 50_000,
) -> SignatureCache:
    """Build and cache signatures keyed by `(table_name, column_name)`."""
    cache: SignatureCache = {}

    for table in tables:
        row_count = table.df.height
        for column_name in table.df.columns:
            series = table.df.get_column(column_name)
            name_features = _build_name_features(column_name)
            null_count = series.null_count()
            non_null_count = row_count - null_count
            distinct_count = series.drop_nulls().n_unique()
            uniqueness_ratio = 0.0 if non_null_count == 0 else distinct_count / non_null_count

            sampled_unique_set = _sampled_unique_values(
                series=series,
                table_name=table.name,
                column_name=column_name,
                name_features=name_features,
                sample_rows=sample_rows,
                sample_seed=sample_seed,
                sampled_unique_cap=sampled_unique_cap,
            )

            cache[(table.name, column_name)] = ColumnSignature(
                table_name=table.name,
                column_name=column_name,
                dtype=table.df.schema[column_name],
                sampled_unique_set=sampled_unique_set,
                sampled_distinct_count=len(sampled_unique_set),
                distinct_count=int(distinct_count),
                uniqueness_ratio=float(uniqueness_ratio),
                non_null_count=int(non_null_count),
                row_count=int(row_count),
                name_features=name_features,
            )

    return cache
