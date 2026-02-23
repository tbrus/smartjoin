"""Primary/composite key discovery with bounded search."""

from __future__ import annotations

import itertools

import polars as pl

from smartjoin.models import KeyCandidate, Table, TableKeyDiscovery


def _candidate_score(uniqueness_ratio: float, null_row_pct: float) -> float:
    """Score a key candidate with uniqueness as the dominant signal."""
    return max(0.0, min(1.0, 0.8 * uniqueness_ratio + 0.2 * (1.0 - null_row_pct)))


def _evaluate_columns(df: pl.DataFrame, columns: list[str]) -> tuple[float, float]:
    """Return `(uniqueness_ratio, null_row_pct)` for candidate columns."""
    row_count = df.height
    if row_count == 0:
        return 0.0, 1.0

    subset = df.select(columns)
    null_mask = pl.any_horizontal([pl.col(col).is_null() for col in columns])
    non_null_subset = subset.filter(~null_mask)
    non_null_count = non_null_subset.height

    if non_null_count == 0:
        return 0.0, 1.0

    unique_count = non_null_subset.unique().height
    uniqueness_ratio = unique_count / non_null_count
    null_row_pct = (row_count - non_null_count) / row_count
    return float(uniqueness_ratio), float(null_row_pct)


def _build_candidate(
    table_name: str,
    columns: list[str],
    df: pl.DataFrame,
    rationale: str,
    metrics_cache: dict[tuple[str, ...], tuple[float, float]] | None = None,
) -> KeyCandidate:
    cache_key = tuple(columns)
    if metrics_cache is not None and cache_key in metrics_cache:
        uniqueness_ratio, null_row_pct = metrics_cache[cache_key]
    else:
        uniqueness_ratio, null_row_pct = _evaluate_columns(df=df, columns=columns)
        if metrics_cache is not None:
            metrics_cache[cache_key] = (uniqueness_ratio, null_row_pct)
    return KeyCandidate(
        table_name=table_name,
        columns=columns,
        uniqueness_ratio=uniqueness_ratio,
        null_row_pct=null_row_pct,
        score=_candidate_score(uniqueness_ratio=uniqueness_ratio, null_row_pct=null_row_pct),
        rationale=rationale,
    )


def discover_keys(
    tables: list[Table],
    min_single_uniqueness: float = 0.98,
    min_composite_uniqueness: float = 0.995,
    near_unique_seed_threshold: float = 0.90,
    max_composite_width: int = 2,
    max_combinations: int = 100,
) -> list[TableKeyDiscovery]:
    """Discover single-column and bounded composite key candidates."""
    discoveries: list[TableKeyDiscovery] = []

    for table in tables:
        df = table.df
        metrics_cache: dict[tuple[str, ...], tuple[float, float]] = {}
        primary_candidates: list[KeyCandidate] = []
        composite_candidates: list[KeyCandidate] = []

        for column in df.columns:
            candidate = _build_candidate(
                table_name=table.name,
                columns=[column],
                df=df,
                rationale="Single-column uniqueness/null check.",
                metrics_cache=metrics_cache,
            )
            if candidate.uniqueness_ratio >= min_single_uniqueness:
                primary_candidates.append(candidate)

        ranked_columns: list[tuple[str, float]] = []
        for column in df.columns:
            cache_key = (column,)
            if cache_key in metrics_cache:
                uniq_ratio, _ = metrics_cache[cache_key]
            else:
                uniq_ratio, _ = _evaluate_columns(df=df, columns=[column])
                metrics_cache[cache_key] = (uniq_ratio, _)
            ranked_columns.append((column, uniq_ratio))
        ranked_columns.sort(key=lambda item: (-item[1], item[0].lower()))

        ratio_by_column = {name: ratio for name, ratio in ranked_columns}
        near_unique_seeds = {
            name for name, ratio in ranked_columns if ratio >= near_unique_seed_threshold
        }
        candidate_columns = [name for name in df.columns if ratio_by_column[name] >= 0.2]
        combinations_checked = 0

        for width in range(2, max_composite_width + 1):
            for combo in itertools.combinations(candidate_columns, width):
                if near_unique_seeds and not any(col in near_unique_seeds for col in combo):
                    continue
                combinations_checked += 1
                if combinations_checked > max_combinations:
                    break
                candidate = _build_candidate(
                    table_name=table.name,
                    columns=list(combo),
                    df=df,
                    rationale=(
                        "Bounded composite uniqueness search seeded by near-unique columns."
                    ),
                    metrics_cache=metrics_cache,
                )
                if candidate.uniqueness_ratio >= min_composite_uniqueness:
                    composite_candidates.append(candidate)
            if combinations_checked > max_combinations:
                break

        primary_candidates = sorted(
            primary_candidates,
            key=lambda c: (-c.score, c.null_row_pct, c.columns),
        )
        composite_candidates = sorted(
            composite_candidates,
            key=lambda c: (-c.score, c.null_row_pct, c.columns),
        )

        discoveries.append(
            TableKeyDiscovery(
                table_name=table.name,
                primary_key_candidates=primary_candidates[:10],
                composite_key_candidates=composite_candidates[:10],
            )
        )

    return sorted(discoveries, key=lambda d: d.table_name.lower())
