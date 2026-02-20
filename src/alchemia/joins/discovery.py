"""Join candidate discovery using cached signatures and safer scoring."""

from __future__ import annotations

import itertools
from difflib import SequenceMatcher

import polars as pl

from alchemia.config import (
    DEFAULT_DISTINCT_LOW_CARD_THRESHOLD,
    DEFAULT_NEAR_UNIQUE_THRESHOLD,
    merge_date_caps,
)
from alchemia.joins.signatures import (
    ColumnSignature,
    SignatureCache,
    build_column_signatures,
)
from alchemia.models import JoinCandidate, JoinScoreBreakdown, Table

DEFAULT_JOIN_WEIGHTS: dict[str, float] = {
    "type_compatibility": 0.16,
    "name_similarity": 0.12,
    "identifier_anchor": 0.08,
    "inclusion_fk_in_pk": 0.32,
    "jaccard": 0.10,
    "cardinality_alignment": 0.10,
    "date_dimension_signal": 0.05,
    "spurious_guard": 0.07,
}


def _is_identifier(sig: ColumnSignature) -> bool:
    return sig.name_features.identifier_like


def _normalize_weights(overrides: dict[str, float] | None = None) -> dict[str, float]:
    merged = dict(DEFAULT_JOIN_WEIGHTS)
    if overrides:
        for key, value in overrides.items():
            if key in merged and value >= 0:
                merged[key] = value
    total = sum(merged.values())
    if total <= 0:
        return dict(DEFAULT_JOIN_WEIGHTS)
    return {key: value / total for key, value in merged.items()}


def _type_compatibility(left: pl.DataType, right: pl.DataType) -> float:
    if left == right:
        return 1.0
    if left.is_numeric() and right.is_numeric():
        return 0.85
    if left == pl.Utf8 and right == pl.Utf8:
        return 1.0
    if left.is_temporal() and right.is_temporal():
        return 0.8
    return 0.0


def _name_similarity(left: ColumnSignature, right: ColumnSignature) -> float:
    return float(
        SequenceMatcher(
            None,
            left.name_features.normalized,
            right.name_features.normalized,
        ).ratio()
    )


def _estimated_inclusion(left: ColumnSignature, right: ColumnSignature) -> float:
    """Estimate containment `left ⊆ right` using sampled distinct sets."""
    if not left.sampled_unique_set or not right.sampled_unique_set:
        return 0.0

    intersection = len(left.sampled_unique_set & right.sampled_unique_set)
    if intersection == 0:
        return 0.0

    left_sample_size = left.sampled_distinct_count
    right_sample_size = right.sampled_distinct_count
    if left_sample_size == 0 or right_sample_size == 0:
        return 0.0

    raw = intersection / left_sample_size
    right_coverage = min(1.0, right_sample_size / max(right.distinct_count, 1))
    if right_coverage <= 0:
        return raw

    # Avoid over-amplifying tiny random overlaps when right-side coverage is low.
    min_overlap = max(3, int(0.01 * left_sample_size))
    if intersection < min_overlap:
        return raw

    adjusted = raw / right_coverage
    return max(0.0, min(1.0, max(raw, adjusted)))


def _jaccard(left_set: frozenset[object], right_set: frozenset[object]) -> float:
    union = left_set | right_set
    if not union:
        return 0.0
    return len(left_set & right_set) / len(union)


def _identifier_anchor(fk: ColumnSignature, pk: ColumnSignature, name_similarity: float) -> float:
    fk_id = _is_identifier(fk)
    pk_id = _is_identifier(pk)
    if fk_id and pk_id:
        return 1.0
    if (fk_id or pk_id) and name_similarity >= 0.8:
        return 0.6
    if fk.name_features.code_like and pk.name_features.code_like and name_similarity >= 0.85:
        return 0.5
    return 0.0


def _build_identifier_hubs(signatures: SignatureCache) -> dict[str, tuple[str, str]]:
    """Pick one hub column per shared identifier name group."""
    grouped: dict[str, list[ColumnSignature]] = {}
    for sig in signatures.values():
        if not _is_identifier(sig):
            continue
        group_key = sig.name_features.entity_core or sig.name_features.normalized
        grouped.setdefault(group_key, []).append(sig)

    hubs: dict[str, tuple[str, str]] = {}
    for normalized, columns in grouped.items():
        if len(columns) < 3:
            continue

        def _table_affinity(sig: ColumnSignature) -> float:
            table_norm = "".join(ch for ch in sig.table_name.lower() if ch.isalnum())
            id_core = sig.name_features.entity_core
            if not id_core:
                return 0.0
            if table_norm == id_core or table_norm == f"{id_core}s":
                return 1.0
            if table_norm.endswith("s") and table_norm[:-1] == id_core:
                return 1.0
            return SequenceMatcher(None, table_norm, id_core).ratio()

        def _quality(sig: ColumnSignature) -> tuple[int, int, int, int, int]:
            tokens = set(sig.name_features.tokens)
            has_alt = int(any(token in {"alt", "legacy", "old"} for token in tokens))
            has_abbrev = int(any(token in {"acct", "cust"} for token in tokens))
            return (
                1 - has_alt,
                1 - has_abbrev,
                int("id" in tokens),
                int(sig.column_name.lower().endswith("_id")),
                int("key" in tokens),
            )

        hub = sorted(
            columns,
            key=lambda sig: (
                _table_affinity(sig),
                *_quality(sig),
                sig.uniqueness_ratio,
                sig.distinct_count,
                -sig.row_count,
                -len(sig.column_name),
            ),
            reverse=True,
        )[0]
        hubs[normalized] = (hub.table_name, hub.column_name)
    return hubs


def _is_categorical(sig: ColumnSignature, distinct_low_card_threshold: int) -> bool:
    if _is_identifier(sig):
        return False
    if sig.row_count == 0:
        return False
    distinct_ratio = sig.distinct_count / sig.row_count
    if sig.distinct_count <= distinct_low_card_threshold:
        return True
    return (
        distinct_ratio <= 0.02
        and sig.distinct_count <= max(256, distinct_low_card_threshold * 4)
    )


def _is_measure_like(sig: ColumnSignature) -> bool:
    """Heuristic for numeric metric columns that are usually not join keys."""
    if _is_identifier(sig) or sig.name_features.date_like:
        return False
    if not sig.dtype.is_numeric():
        return False
    measure_tokens = {
        "amount",
        "price",
        "qty",
        "quantity",
        "total",
        "count",
        "number",
        "line",
        "unit",
        "units",
        "cost",
        "value",
        "pct",
        "percent",
        "score",
        "rate",
    }
    tokens = set(sig.name_features.tokens)
    return bool(tokens & measure_tokens)


def _table_base_name(table_name: str) -> str:
    lowered = table_name.lower()
    for suffix in ("_nested", "_json", "_flat", "_raw", "_export"):
        if lowered.endswith(suffix):
            return lowered[: -len(suffix)]
    return lowered


def _is_mirror_pair(left_table: str, right_table: str) -> bool:
    left_base = _table_base_name(left_table)
    right_base = _table_base_name(right_table)
    return left_base == right_base and left_table.lower() != right_table.lower()


def _build_table_identifier_winners(
    signatures: SignatureCache,
) -> dict[tuple[str, str], tuple[str, str]]:
    """
    Pick one canonical identifier column per `(table, entity_core)` group.

    This suppresses alternate IDs such as `acct_id`/`cust_id` when a clearer
    canonical key exists in the same table.
    """
    groups: dict[tuple[str, str], list[ColumnSignature]] = {}
    for sig in signatures.values():
        if not _is_identifier(sig):
            continue
        entity_core = sig.name_features.entity_core
        if not entity_core:
            continue
        groups.setdefault((sig.table_name, entity_core), []).append(sig)

    winners: dict[tuple[str, str], tuple[str, str]] = {}
    for key, cols in groups.items():
        def _quality(sig: ColumnSignature) -> tuple[int, int, int, int, int]:
            tokens = set(sig.name_features.tokens)
            has_alt = int(any(token in {"alt", "legacy", "old"} for token in tokens))
            has_abbrev = int(any(token in {"acct", "cust"} for token in tokens))
            return (
                1 - has_alt,
                1 - has_abbrev,
                int("id" in tokens),
                int(sig.column_name.lower().endswith("_id")),
                int("key" in tokens),
            )

        winner = sorted(
            cols,
            key=lambda sig: (
                *_quality(sig),
                sig.uniqueness_ratio,
                sig.distinct_count,
                -len(sig.column_name),
            ),
            reverse=True,
        )[0]
        winners[key] = (winner.table_name, winner.column_name)
    return winners


def _canonical_identifier_penalty(
    sig: ColumnSignature,
    table_identifier_winners: dict[tuple[str, str], tuple[str, str]],
) -> float:
    if not _is_identifier(sig):
        return 1.0
    entity_core = sig.name_features.entity_core
    if not entity_core:
        return 1.0
    winner = table_identifier_winners.get((sig.table_name, entity_core))
    if winner is None:
        return 1.0
    self_key = (sig.table_name, sig.column_name)
    if self_key == winner:
        return 1.0
    if any(token in {"alt", "legacy", "old"} for token in sig.name_features.tokens):
        return 0.2
    if any(token in {"acct", "cust"} for token in sig.name_features.tokens):
        return 0.4
    return 0.6


def _spurious_guard(
    fk: ColumnSignature,
    pk: ColumnSignature,
    name_similarity: float,
    inclusion_fk_in_pk: float,
    sibling_non_hub: bool,
    mirror_pair: bool,
    canonical_penalty: float,
    distinct_low_card_threshold: int,
) -> float:
    if fk.row_count == 0 or pk.row_count == 0:
        return 0.0

    fk_ratio = fk.sampled_distinct_count / max(fk.row_count, 1)
    pk_ratio = pk.sampled_distinct_count / max(pk.row_count, 1)

    is_date_pair = fk.name_features.date_like and pk.name_features.date_like

    if sibling_non_hub:
        return 0.0
    if mirror_pair and _is_identifier(fk) and _is_identifier(pk):
        return 0.0
    if mirror_pair and fk.name_features.date_like and pk.name_features.date_like:
        return 0.0
    if _is_measure_like(fk) and _is_measure_like(pk) and name_similarity < 0.95:
        return 0.0
    # Allow specific code-domain joins (e.g. diagnosis_code -> code dimension)
    # when both sides clearly refer to the same non-generic code namespace.
    generic_code_entities = {"status", "country", "currency", "type", "category"}
    same_specific_code_domain = (
        fk.name_features.code_like
        and pk.name_features.code_like
        and fk.name_features.entity_core
        and fk.name_features.entity_core == pk.name_features.entity_core
        and fk.name_features.entity_core not in generic_code_entities
        and name_similarity >= 0.8
        and inclusion_fk_in_pk >= 0.9
        and pk.uniqueness_ratio >= 0.9
    )
    if same_specific_code_domain:
        return canonical_penalty
    if not is_date_pair and _is_categorical(
        fk, distinct_low_card_threshold
    ) and _is_categorical(pk, distinct_low_card_threshold):
        return 0.0
    fk_identifier = _is_identifier(fk)
    pk_identifier = _is_identifier(pk)
    if (
        not fk_identifier
        and not pk_identifier
        and fk.sampled_distinct_count <= 20
        and pk.sampled_distinct_count <= 20
    ):
        return 0.0
    if (
        not fk_identifier
        and not pk_identifier
        and fk_ratio <= 0.05
        and pk_ratio <= 0.05
    ):
        return 0.0
    if (
        not fk_identifier
        and not pk_identifier
        and name_similarity < 0.55
        and inclusion_fk_in_pk < 0.95
    ):
        return 0.0
    return canonical_penalty


def _detect_bridge_tables(
    tables: list[Table],
    signatures: SignatureCache,
) -> set[str]:
    """
    Detect bridge tables by looking for two id-like columns that are individually
    non-unique but jointly near-unique.
    """
    bridges: set[str] = set()
    for table in tables:
        id_cols = [
            col
            for col in table.df.columns
            if _is_identifier(signatures[(table.name, col)])
        ]
        if len(id_cols) < 2:
            continue

        # Prefer plausible FK-like id columns that are not individually unique.
        fk_like = [
            col
            for col in id_cols
            if 0.05 <= signatures[(table.name, col)].uniqueness_ratio < 0.98
        ]
        if len(fk_like) < 2:
            continue

        # Bound the search to avoid expensive pair scans on very wide tables.
        selected = fk_like[:6]
        for left_col, right_col in itertools.combinations(selected, 2):
            subset = table.df.select([left_col, right_col])
            null_mask = pl.any_horizontal([pl.col(left_col).is_null(), pl.col(right_col).is_null()])
            non_null_subset = subset.filter(~null_mask)
            non_null_count = non_null_subset.height
            if non_null_count == 0:
                continue
            combined_uniqueness = non_null_subset.unique().height / non_null_count
            if combined_uniqueness >= 0.98:
                bridges.add(table.name)
                break
        if table.name in bridges:
            continue
    return bridges


def _date_signal_and_cap(
    fk: ColumnSignature,
    pk: ColumnSignature,
    inclusion_fk_in_pk: float,
    date_caps: dict[str, float],
) -> tuple[float, float, str | None]:
    """Return `(date_signal, confidence_cap, relationship_override)`."""
    temporal_overlap_cap = float(date_caps["temporal_overlap"])
    mixed_temporal_cap = float(date_caps["mixed_temporal"])
    temporal_overlap_signal = float(date_caps["temporal_overlap_signal"])
    mixed_temporal_signal = float(date_caps["mixed_temporal_signal"])

    if not (fk.name_features.date_like and pk.name_features.date_like):
        return 1.0, 1.0, None

    # Surrogate keys such as `date_key` should not be treated as raw temporal overlaps.
    if (
        (fk.name_features.key_like or fk.name_features.id_like)
        and (pk.name_features.key_like or pk.name_features.id_like)
    ):
        return 1.0, 1.0, None

    def _temporal_role(tokens: tuple[str, ...]) -> str:
        token_set = set(tokens)
        if "start" in token_set or "end" in token_set:
            return "range_boundary"
        if token_set & {"created", "updated", "shipped", "delivered", "applied"}:
            return "audit_like"
        if "date" in token_set and len(token_set) <= 2:
            return "calendar_like"
        return "temporal_other"

    # Typical calendar/date-dimension pattern.
    if (
        pk.uniqueness_ratio >= 0.95
        and fk.uniqueness_ratio <= 0.7
        and inclusion_fk_in_pk >= 0.85
        and fk.row_count >= (pk.row_count * 2)
    ):
        return 1.0, 1.0, "date_dimension_join"

    # Unique-to-unique date columns across tables are commonly coincidental and
    # should be inspectable but not promoted above conservative defaults.
    if fk.uniqueness_ratio >= 0.95 and pk.uniqueness_ratio >= 0.95:
        return mixed_temporal_signal, min(mixed_temporal_cap, 0.68), "temporal_overlap"

    # Mismatched temporal roles (e.g., `created_date` vs `end_date`) are usually
    # coincidental overlaps and should stay below conservative default thresholds.
    fk_role = _temporal_role(fk.name_features.tokens)
    pk_role = _temporal_role(pk.name_features.tokens)
    if fk_role != pk_role and {"range_boundary", "audit_like"} & {fk_role, pk_role}:
        return mixed_temporal_signal, min(mixed_temporal_cap, 0.62), "temporal_overlap"

    # Keep temporal overlaps inspectable but capped to avoid dominating true key joins.
    if fk.uniqueness_ratio <= 0.5 and pk.uniqueness_ratio <= 0.5:
        return temporal_overlap_signal, temporal_overlap_cap, "temporal_overlap"

    return mixed_temporal_signal, mixed_temporal_cap, "temporal_overlap"


def _cardinality_alignment(fk_uniqueness: float, pk_uniqueness: float) -> float:
    """Prefer FK uniqueness <= PK uniqueness."""
    if pk_uniqueness >= fk_uniqueness:
        return 1.0
    gap = fk_uniqueness - pk_uniqueness
    return max(0.0, 1.0 - (2.0 * gap))


def _weighted_score(signals: dict[str, float], weights: dict[str, float]) -> float:
    score = 0.0
    for name, weight in weights.items():
        score += signals.get(name, 0.0) * weight
    return max(0.0, min(1.0, float(score)))


def _normalize_direction(
    left: ColumnSignature,
    right: ColumnSignature,
    inclusion_lr: float,
    inclusion_rl: float,
) -> tuple[ColumnSignature, ColumnSignature, float, float]:
    """
    Normalize direction as FK-like -> PK-like.

    Returns `(fk_sig, pk_sig, inclusion_fk_in_pk, inclusion_pk_in_fk)`.
    """
    inclusion_margin = 0.02
    if inclusion_lr - inclusion_rl > inclusion_margin:
        return left, right, inclusion_lr, inclusion_rl
    if inclusion_rl - inclusion_lr > inclusion_margin:
        return right, left, inclusion_rl, inclusion_lr

    if left.uniqueness_ratio < right.uniqueness_ratio:
        return left, right, inclusion_lr, inclusion_rl
    if right.uniqueness_ratio < left.uniqueness_ratio:
        return right, left, inclusion_rl, inclusion_lr

    left_key = (left.table_name.lower(), left.column_name.lower())
    right_key = (right.table_name.lower(), right.column_name.lower())
    if left_key <= right_key:
        return left, right, inclusion_lr, inclusion_rl
    return right, left, inclusion_rl, inclusion_lr


def _relationship_guess(
    fk: ColumnSignature,
    pk: ColumnSignature,
    bridge_tables: set[str],
    date_override: str | None = None,
) -> str:
    if date_override is not None:
        return date_override
    if (
        fk.table_name in bridge_tables
        and _is_identifier(fk)
        and _is_identifier(pk)
        and pk.uniqueness_ratio >= 0.98
    ):
        return "bridge_to_dimension"
    if fk.uniqueness_ratio >= 0.98 and pk.uniqueness_ratio >= 0.98:
        return "one_to_one"
    if fk.uniqueness_ratio < 0.98 and pk.uniqueness_ratio >= 0.98:
        return "many_to_one"
    if fk.uniqueness_ratio >= 0.98 and pk.uniqueness_ratio < 0.98:
        return "one_to_many"
    return "many_to_many"


def find_join_candidates(
    tables: list[Table],
    sample_rows: int = 10_000,
    min_confidence: float = 0.8,
    weights: dict[str, float] | None = None,
    sample_seed: int = 42,
    near_unique_threshold: float = DEFAULT_NEAR_UNIQUE_THRESHOLD,
    distinct_low_card_threshold: int = DEFAULT_DISTINCT_LOW_CARD_THRESHOLD,
    date_caps: dict[str, float] | None = None,
    signature_cache: SignatureCache | None = None,
) -> list[JoinCandidate]:
    """Find join candidates using cached column signatures."""
    normalized_weights = _normalize_weights(weights)
    effective_date_caps = merge_date_caps(date_caps)
    signatures = signature_cache or build_column_signatures(
        tables=tables,
        sample_rows=sample_rows,
        sample_seed=sample_seed,
    )
    identifier_hubs = _build_identifier_hubs(signatures)
    table_identifier_winners = _build_table_identifier_winners(signatures)
    bridge_tables = _detect_bridge_tables(tables=tables, signatures=signatures)
    near_unique_by_table = {
        table.name: {
            col
            for col in table.df.columns
            if signatures[(table.name, col)].uniqueness_ratio >= near_unique_threshold
        }
        for table in tables
    }
    candidates: list[JoinCandidate] = []

    for left_table, right_table in itertools.combinations(tables, 2):
        mirror_pair = _is_mirror_pair(left_table.name, right_table.name)
        for left_col in left_table.df.columns:
            left_sig = signatures[(left_table.name, left_col)]
            if not left_sig.sampled_unique_set:
                continue

            for right_col in right_table.df.columns:
                right_sig = signatures[(right_table.name, right_col)]
                if not right_sig.sampled_unique_set:
                    continue

                if (
                    near_unique_by_table[left_table.name]
                    and near_unique_by_table[right_table.name]
                    and left_col not in near_unique_by_table[left_table.name]
                    and right_col not in near_unique_by_table[right_table.name]
                    and not _is_identifier(left_sig)
                    and not _is_identifier(right_sig)
                    and not (left_sig.name_features.date_like and right_sig.name_features.date_like)
                ):
                    continue

                type_score = _type_compatibility(left_sig.dtype, right_sig.dtype)
                if type_score == 0.0:
                    continue

                overlap = left_sig.sampled_unique_set & right_sig.sampled_unique_set
                if not overlap:
                    continue

                inclusion_lr = _estimated_inclusion(left_sig, right_sig)
                inclusion_rl = _estimated_inclusion(right_sig, left_sig)
                fk_sig, pk_sig, inclusion_fk_in_pk, inclusion_pk_in_fk = _normalize_direction(
                    left=left_sig,
                    right=right_sig,
                    inclusion_lr=inclusion_lr,
                    inclusion_rl=inclusion_rl,
                )
                name_similarity = _name_similarity(fk_sig, pk_sig)
                identifier_anchor = _identifier_anchor(
                    fk=fk_sig,
                    pk=pk_sig,
                    name_similarity=name_similarity,
                )
                sibling_non_hub = False
                if (
                    _is_identifier(fk_sig)
                    and _is_identifier(pk_sig)
                    and fk_sig.name_features.entity_core
                    and fk_sig.name_features.entity_core == pk_sig.name_features.entity_core
                ):
                    hub_group = fk_sig.name_features.entity_core or fk_sig.name_features.normalized
                    hub_key = identifier_hubs.get(hub_group)
                    if hub_key is not None:
                        fk_key = (fk_sig.table_name, fk_sig.column_name)
                        pk_key = (pk_sig.table_name, pk_sig.column_name)
                        sibling_non_hub = fk_key != hub_key and pk_key != hub_key
                spurious_guard = _spurious_guard(
                    fk=fk_sig,
                    pk=pk_sig,
                    name_similarity=name_similarity,
                    inclusion_fk_in_pk=inclusion_fk_in_pk,
                    sibling_non_hub=sibling_non_hub,
                    mirror_pair=mirror_pair,
                    canonical_penalty=(
                        _canonical_identifier_penalty(
                            sig=fk_sig,
                            table_identifier_winners=table_identifier_winners,
                        )
                        * _canonical_identifier_penalty(
                            sig=pk_sig,
                            table_identifier_winners=table_identifier_winners,
                        )
                    ),
                    distinct_low_card_threshold=distinct_low_card_threshold,
                )
                if spurious_guard == 0.0:
                    continue
                date_dimension_signal, date_cap, date_override = _date_signal_and_cap(
                    fk=fk_sig,
                    pk=pk_sig,
                    inclusion_fk_in_pk=inclusion_fk_in_pk,
                    date_caps=effective_date_caps,
                )

                signals = {
                    "type_compatibility": type_score,
                    "name_similarity": name_similarity,
                    "identifier_anchor": identifier_anchor,
                    "inclusion_fk_in_pk": inclusion_fk_in_pk,
                    "inclusion_pk_in_fk": inclusion_pk_in_fk,
                    "jaccard": _jaccard(fk_sig.sampled_unique_set, pk_sig.sampled_unique_set),
                    "cardinality_alignment": _cardinality_alignment(
                        fk_uniqueness=fk_sig.uniqueness_ratio,
                        pk_uniqueness=pk_sig.uniqueness_ratio,
                    ),
                    "date_dimension_signal": date_dimension_signal,
                    "spurious_guard": spurious_guard,
                }

                confidence = _weighted_score(signals=signals, weights=normalized_weights)
                confidence = min(confidence, date_cap)
                if confidence < min_confidence:
                    continue

                candidates.append(
                    JoinCandidate(
                        left_table=fk_sig.table_name,
                        left_column=fk_sig.column_name,
                        right_table=pk_sig.table_name,
                        right_column=pk_sig.column_name,
                        confidence=confidence,
                        relationship_guess=_relationship_guess(
                            fk=fk_sig,
                            pk=pk_sig,
                            bridge_tables=bridge_tables,
                            date_override=date_override,
                        ),
                        breakdown=JoinScoreBreakdown(
                            signals={key: float(value) for key, value in signals.items()},
                            weights={
                                key: float(value) for key, value in normalized_weights.items()
                            },
                            weighted_score=confidence,
                        ),
                    )
                )

    return sorted(
        candidates,
        key=lambda candidate: (
            -candidate.confidence,
            candidate.left_table.lower(),
            candidate.left_column.lower(),
            candidate.right_table.lower(),
            candidate.right_column.lower(),
        ),
    )
