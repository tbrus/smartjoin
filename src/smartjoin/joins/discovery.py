"""Join candidate discovery using cached signatures and safer scoring."""

from __future__ import annotations

import itertools
from difflib import SequenceMatcher

import polars as pl

from smartjoin.config import (
    DEFAULT_DISTINCT_LOW_CARD_THRESHOLD,
    DEFAULT_NEAR_UNIQUE_THRESHOLD,
    DERIVED_CONF_MULT,
    DERIVED_JOINS_ENABLED,
    DERIVED_MAX_AMBIGUOUS_TARGETS,
    DERIVED_MAX_COLUMNS_PER_TABLE,
    DERIVED_MAX_TRANSFORMS_PER_COLUMN,
    DERIVED_MIN_DISTINCT,
    merge_date_caps,
)
from smartjoin.joins.derived import (
    DerivedBudgets,
    DerivedCandidate,
    detect_dominant_value_prefix,
    derive_candidates_for_column,
    entity_cores_compatible,
    normalize_transformed_value_for_signature,
    rank_derived_source_columns,
    transform_description,
)
from smartjoin.joins.signatures import (
    ColumnSignature,
    SignatureCache,
    build_column_signatures,
)
from smartjoin.models import DerivedTransform, JoinCandidate, JoinScoreBreakdown, Table

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


def _contains_short_abbreviation(tokens: set[str]) -> bool:
    qualifiers = {
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
    return any(token not in qualifiers and len(token) <= 3 for token in tokens)


def _is_identifier(sig: ColumnSignature) -> bool:
    return sig.name_features.identifier_like


def _is_keylike(sig: ColumnSignature) -> bool:
    return sig.name_features.identifier_like or sig.name_features.code_like


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
    """Estimate containment using sampled distinct sets."""
    return _estimated_inclusion_from_sets(
        left_set=left.sampled_unique_set,
        right_set=right.sampled_unique_set,
        right_distinct_count=right.distinct_count,
    )


def _estimated_inclusion_from_sets(
    left_set: frozenset[object],
    right_set: frozenset[object],
    right_distinct_count: int,
) -> float:
    if not left_set or not right_set:
        return 0.0

    intersection = len(left_set & right_set)
    if intersection == 0:
        return 0.0

    left_sample_size = len(left_set)
    right_sample_size = len(right_set)
    if left_sample_size == 0 or right_sample_size == 0:
        return 0.0

    raw = intersection / left_sample_size
    right_coverage = min(1.0, right_sample_size / max(right_distinct_count, 1))
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
            has_abbrev = int(_contains_short_abbreviation(tokens))
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

    This suppresses alternate ID abbreviations when a clearer
    canonical key exists in the same table.
    """
    def _entity_core_compatible_text(left_core: str, right_core: str) -> bool:
        left = left_core.strip().lower()
        right = right_core.strip().lower()
        if not left or not right:
            return False
        if left == right:
            return True
        if left.startswith(right) or right.startswith(left):
            return True
        if min(len(left), len(right)) >= 3:
            return SequenceMatcher(None, left, right).ratio() >= 0.72
        return False

    by_table: dict[str, list[ColumnSignature]] = {}
    for sig in signatures.values():
        if not _is_identifier(sig):
            continue
        if not sig.name_features.entity_core:
            continue
        by_table.setdefault(sig.table_name, []).append(sig)

    winners: dict[tuple[str, str], tuple[str, str]] = {}
    for table_name, table_cols in by_table.items():
        core_groups: list[list[ColumnSignature]] = []
        for sig in table_cols:
            matched_group: list[ColumnSignature] | None = None
            for group in core_groups:
                if any(
                    _entity_core_compatible_text(
                        sig.name_features.entity_core,
                        member.name_features.entity_core,
                    )
                    for member in group
                ):
                    matched_group = group
                    break
            if matched_group is None:
                core_groups.append([sig])
            else:
                matched_group.append(sig)

        def _quality(sig: ColumnSignature) -> tuple[int, int, int, int, int]:
            tokens = set(sig.name_features.tokens)
            has_alt = int(any(token in {"alt", "legacy", "old"} for token in tokens))
            has_abbrev = int(_contains_short_abbreviation(tokens))
            return (
                1 - has_alt,
                1 - has_abbrev,
                int("id" in tokens),
                int(sig.column_name.lower().endswith("_id")),
                int("key" in tokens),
            )

        for group in core_groups:
            winner = sorted(
                group,
                key=lambda sig: (
                    *_quality(sig),
                    len(sig.name_features.entity_core),
                    sig.uniqueness_ratio,
                    sig.distinct_count,
                    len(sig.column_name),
                ),
                reverse=True,
            )[0]
            winner_key = (winner.table_name, winner.column_name)
            for member in group:
                winners[(table_name, member.name_features.entity_core)] = winner_key
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
    if _contains_short_abbreviation(set(sig.name_features.tokens)):
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


def _is_preferred_fk_direction(fk: ColumnSignature, pk: ColumnSignature) -> bool:
    if fk.uniqueness_ratio < pk.uniqueness_ratio:
        return True
    if pk.uniqueness_ratio < fk.uniqueness_ratio:
        return False
    fk_key = (fk.table_name.lower(), fk.column_name.lower())
    pk_key = (pk.table_name.lower(), pk.column_name.lower())
    return fk_key <= pk_key


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


def _derived_pair_prefilter(
    left_sig: ColumnSignature,
    right_sig: ColumnSignature,
    name_similarity: float,
) -> bool:
    if left_sig.name_features.date_like or right_sig.name_features.date_like:
        return False
    if left_sig.dtype.is_temporal() or right_sig.dtype.is_temporal():
        return False
    left_key = _is_keylike(left_sig)
    right_key = _is_keylike(right_sig)
    if not ((left_key and right_key) or ((left_key or right_key) and name_similarity >= 0.8)):
        return False
    return entity_cores_compatible(left_sig, right_sig)


def _normalize_transformed_values_for_target(
    transformed_values: frozenset[str],
    target_sig: ColumnSignature,
) -> frozenset[object]:
    if not transformed_values:
        return frozenset()
    normalized = {
        normalize_transformed_value_for_signature(value, signature=target_sig)
        for value in transformed_values
    }
    return frozenset(normalized)


def _dominant_prefix_from_values(values: frozenset[object]) -> str | None:
    text_values: list[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            text_values.append(text)
    if not text_values:
        return None
    return detect_dominant_value_prefix(text_values)


def _value_prefix_similarity(left_prefix: str, right_prefix: str) -> float:
    left = left_prefix.strip().lower()
    right = right_prefix.strip().lower()
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if left.startswith(right) or right.startswith(left):
        return 0.85
    if left in right or right in left:
        return 0.75
    return float(SequenceMatcher(None, left, right).ratio())


def _derived_fallback_rank_limit(max_columns_per_table: int) -> int:
    base = max(1, int(max_columns_per_table))
    return base + max(2, base)


def _get_or_build_derived_variants(
    *,
    source_sig: ColumnSignature,
    target_sig: ColumnSignature,
    source_table: Table,
    sample_rows: int,
    sample_seed: int,
    budgets: DerivedBudgets,
    derived_cache: dict[tuple[str, str], list[DerivedCandidate]],
    derived_attempted: set[tuple[str, str]],
    derived_rank_index: dict[tuple[str, str], int],
    name_similarity: float,
) -> list[DerivedCandidate]:
    source_key = (source_sig.table_name, source_sig.column_name)
    cached = derived_cache.get(source_key)
    if cached is not None:
        return cached
    if source_key in derived_attempted:
        return []
    rank = derived_rank_index.get(source_key)
    if rank is None:
        return []
    if rank >= _derived_fallback_rank_limit(budgets.max_columns_per_table):
        return []
    if not _derived_pair_prefilter(
        left_sig=source_sig,
        right_sig=target_sig,
        name_similarity=name_similarity,
    ):
        return []
    variants = derive_candidates_for_column(
        signature=source_sig,
        table_df=source_table.df,
        sample_rows=sample_rows,
        sample_seed=sample_seed,
        budgets=budgets,
    )
    derived_attempted.add(source_key)
    if variants:
        derived_cache[source_key] = variants
    return variants


def _is_plausible_key_col(sig: ColumnSignature, min_distinct: int) -> bool:
    if sig.name_features.date_like:
        return False
    if sig.name_features.identifier_like or sig.name_features.code_like:
        return True
    if sig.row_count <= 0:
        return False
    if sig.distinct_count < max(1, int(min_distinct)):
        return False
    if sig.uniqueness_ratio < 0.2:
        return False
    distinct_ratio = sig.distinct_count / sig.row_count
    if distinct_ratio < 0.05:
        return False
    return True


def _derived_is_ambiguous(
    transformed_fk_values: frozenset[str],
    target_table: Table,
    target_column: str,
    signatures: SignatureCache,
    max_ambiguous_targets: int,
    min_distinct: int,
) -> bool:
    threshold = 0.6
    ambiguous = 0
    for candidate_column in target_table.df.columns:
        if candidate_column == target_column:
            continue
        candidate_sig = signatures[(target_table.name, candidate_column)]
        if not _is_plausible_key_col(candidate_sig, min_distinct=min_distinct):
            continue
        if not candidate_sig.sampled_unique_set:
            continue
        fk_values = _normalize_transformed_values_for_target(
            transformed_values=transformed_fk_values,
            target_sig=candidate_sig,
        )
        if not fk_values:
            continue
        inclusion = _estimated_inclusion_from_sets(
            left_set=fk_values,
            right_set=candidate_sig.sampled_unique_set,
            right_distinct_count=candidate_sig.distinct_count,
        )
        if inclusion >= threshold:
            ambiguous += 1
            if ambiguous > max_ambiguous_targets:
                return True
    return False


def _is_direct_identifier_namespace_collision(
    fk_sig: ColumnSignature,
    pk_sig: ColumnSignature,
    inclusion_fk_in_pk: float,
    inclusion_pk_in_fk: float,
    derived: DerivedTransform | None,
) -> bool:
    """
    Reject highly overlapping direct identifier joins across incompatible namespaces.

    This targets one-to-one numeric-domain collisions such as `payment_id <-> refund_id`
    while preserving valid many-to-one FK->PK joins.
    """
    if derived is not None:
        return False
    if not (_is_identifier(fk_sig) and _is_identifier(pk_sig)):
        return False
    if not (fk_sig.name_features.entity_core and pk_sig.name_features.entity_core):
        return False
    if entity_cores_compatible(fk_sig, pk_sig):
        return False
    if fk_sig.uniqueness_ratio < 0.98 or pk_sig.uniqueness_ratio < 0.98:
        return False
    return inclusion_fk_in_pk >= 0.98 and inclusion_pk_in_fk >= 0.98


def _temporal_signature_equivalent(
    left: ColumnSignature,
    right: ColumnSignature,
) -> bool:
    if not (left.name_features.date_like and right.name_features.date_like):
        return False
    if not left.sampled_unique_set or not right.sampled_unique_set:
        return False
    if _jaccard(left.sampled_unique_set, right.sampled_unique_set) < 0.995:
        return False
    inclusion_lr = _estimated_inclusion_from_sets(
        left_set=left.sampled_unique_set,
        right_set=right.sampled_unique_set,
        right_distinct_count=right.distinct_count,
    )
    inclusion_rl = _estimated_inclusion_from_sets(
        left_set=right.sampled_unique_set,
        right_set=left.sampled_unique_set,
        right_distinct_count=left.distinct_count,
    )
    return inclusion_lr >= 0.995 and inclusion_rl >= 0.995


def _temporal_candidate_preference(
    candidate: JoinCandidate,
    signatures: SignatureCache,
) -> tuple[int, int, float, float, int]:
    fk_sig = signatures[(candidate.left_table, candidate.left_column)]
    pk_sig = signatures[(candidate.right_table, candidate.right_column)]
    fk_idish = fk_sig.name_features.id_like or fk_sig.name_features.key_like
    pk_idish = pk_sig.name_features.id_like or pk_sig.name_features.key_like
    role_match = int(fk_idish == pk_idish)
    pk_plain_date = int("date" in pk_sig.name_features.tokens and not pk_idish)
    return (
        role_match,
        pk_plain_date,
        _name_similarity(fk_sig, pk_sig),
        candidate.confidence,
        -len(pk_sig.column_name),
    )


def _dedupe_temporal_equivalent_targets(
    candidates: list[JoinCandidate],
    signatures: SignatureCache,
) -> list[JoinCandidate]:
    """
    For one FK date-like column into one table, keep one best equivalent temporal target.
    """
    grouped: dict[tuple[str, str, str], list[JoinCandidate]] = {}
    passthrough: list[JoinCandidate] = []
    for candidate in candidates:
        if candidate.derived is not None:
            passthrough.append(candidate)
            continue
        fk_sig = signatures[(candidate.left_table, candidate.left_column)]
        pk_sig = signatures[(candidate.right_table, candidate.right_column)]
        if not (fk_sig.name_features.date_like and pk_sig.name_features.date_like):
            passthrough.append(candidate)
            continue
        group_key = (candidate.left_table, candidate.left_column, candidate.right_table)
        grouped.setdefault(group_key, []).append(candidate)

    deduped: list[JoinCandidate] = []
    for group in grouped.values():
        if len(group) == 1:
            deduped.extend(group)
            continue
        ordered = sorted(
            group,
            key=lambda candidate: _temporal_candidate_preference(candidate, signatures),
            reverse=True,
        )
        kept: list[JoinCandidate] = []
        kept_right_sigs: list[ColumnSignature] = []
        for candidate in ordered:
            candidate_pk = signatures[(candidate.right_table, candidate.right_column)]
            equivalent_to_kept = any(
                _temporal_signature_equivalent(candidate_pk, kept_pk)
                for kept_pk in kept_right_sigs
            )
            if equivalent_to_kept:
                continue
            kept.append(candidate)
            kept_right_sigs.append(candidate_pk)
        deduped.extend(kept)

    deduped.extend(passthrough)
    return deduped


def _dedupe_bidirectional_endpoint_pairs(
    candidates: list[JoinCandidate],
) -> list[JoinCandidate]:
    """
    Keep one best candidate per undirected endpoint pair.

    Prevents duplicate edges for the same two columns in opposite directions.
    """
    best_by_pair: dict[tuple[str, str], JoinCandidate] = {}
    for candidate in candidates:
        pair_key = tuple(
            sorted(
                [
                    f"{candidate.left_table}.{candidate.left_column}".lower(),
                    f"{candidate.right_table}.{candidate.right_column}".lower(),
                ]
            )
        )
        current = best_by_pair.get(pair_key)
        if current is None or _should_replace_candidate(current=current, incoming=candidate):
            best_by_pair[pair_key] = candidate
    return list(best_by_pair.values())


def _drop_dominated_noncanonical_targets(
    candidates: list[JoinCandidate],
    signatures: SignatureCache,
    table_identifier_winners: dict[tuple[str, str], tuple[str, str]],
) -> list[JoinCandidate]:
    """
    Drop non-canonical identifier targets when a stronger canonical sibling exists.

    This suppresses alias/trap columns (e.g. `cust_id`) when the canonical column
    in the same table (e.g. `customer_id`) already explains the same source FK.
    """
    by_group: dict[tuple[str, str, str], list[JoinCandidate]] = {}
    passthrough: list[JoinCandidate] = []
    for candidate in candidates:
        pk_sig = signatures[(candidate.right_table, candidate.right_column)]
        if not _is_identifier(pk_sig):
            passthrough.append(candidate)
            continue
        group_key = (candidate.left_table, candidate.left_column, candidate.right_table)
        by_group.setdefault(group_key, []).append(candidate)

    kept: list[JoinCandidate] = []
    dominance_margin = 0.03
    for group_candidates in by_group.values():
        by_right_col = {candidate.right_column: candidate for candidate in group_candidates}
        for candidate in group_candidates:
            pk_sig = signatures[(candidate.right_table, candidate.right_column)]
            winner = table_identifier_winners.get((pk_sig.table_name, pk_sig.name_features.entity_core))
            if winner is None:
                kept.append(candidate)
                continue
            winner_table, winner_col = winner
            if winner_table != candidate.right_table or winner_col == candidate.right_column:
                kept.append(candidate)
                continue
            canonical_candidate = by_right_col.get(winner_col)
            if canonical_candidate is None:
                kept.append(candidate)
                continue
            if canonical_candidate.confidence >= (candidate.confidence + dominance_margin):
                continue
            kept.append(candidate)

    kept.extend(passthrough)
    return kept


def _drop_noncanonical_alias_edges(
    candidates: list[JoinCandidate],
    signatures: SignatureCache,
    table_identifier_winners: dict[tuple[str, str], tuple[str, str]],
) -> list[JoinCandidate]:
    """
    Suppress alias edges when a stronger canonical sibling edge exists.

    This is orientation-agnostic and compares edges by undirected endpoint pair,
    so `A.alias -> B.key` is dropped when `A.canonical <-> B.key` is stronger.
    """
    dominance_margin = 0.03
    candidate_by_pair: dict[tuple[str, str], JoinCandidate] = {}

    def _endpoint(table: str, column: str) -> str:
        return f"{table}.{column}".lower()

    for candidate in candidates:
        pair_key = tuple(
            sorted(
                [
                    _endpoint(candidate.left_table, candidate.left_column),
                    _endpoint(candidate.right_table, candidate.right_column),
                ]
            )
        )
        candidate_by_pair[pair_key] = candidate

    kept: list[JoinCandidate] = []
    for candidate in candidates:
        drop = False
        left_sig = signatures[(candidate.left_table, candidate.left_column)]
        right_sig = signatures[(candidate.right_table, candidate.right_column)]
        side_specs = (
            (
                candidate.left_table,
                candidate.left_column,
                left_sig,
                _endpoint(candidate.right_table, candidate.right_column),
            ),
            (
                candidate.right_table,
                candidate.right_column,
                right_sig,
                _endpoint(candidate.left_table, candidate.left_column),
            ),
        )
        for table_name, column_name, sig, opposite_endpoint in side_specs:
            if not _is_identifier(sig):
                continue
            entity_core = sig.name_features.entity_core
            if not entity_core:
                continue
            winner = table_identifier_winners.get((table_name, entity_core))
            if winner is None:
                continue
            winner_table, winner_column = winner
            if winner_table != table_name:
                continue
            if winner_column == column_name:
                continue
            canonical_pair_key = tuple(
                sorted([_endpoint(winner_table, winner_column), opposite_endpoint])
            )
            canonical_candidate = candidate_by_pair.get(canonical_pair_key)
            if canonical_candidate is None:
                continue
            if canonical_candidate.confidence >= (candidate.confidence + dominance_margin):
                drop = True
                break
        if drop:
            continue
        kept.append(candidate)
    return kept


def _score_candidate(
    *,
    fk_sig: ColumnSignature,
    pk_sig: ColumnSignature,
    fk_values: frozenset[object],
    pk_values: frozenset[object],
    inclusion_fk_in_pk: float,
    inclusion_pk_in_fk: float,
    type_score: float,
    normalized_weights: dict[str, float],
    effective_date_caps: dict[str, float],
    min_confidence: float,
    identifier_hubs: dict[str, tuple[str, str]],
    table_identifier_winners: dict[tuple[str, str], tuple[str, str]],
    bridge_tables: set[str],
    mirror_pair: bool,
    distinct_low_card_threshold: int,
    derived_conf_mult: float,
    derived: DerivedTransform | None,
) -> JoinCandidate | None:
    if _is_direct_identifier_namespace_collision(
        fk_sig=fk_sig,
        pk_sig=pk_sig,
        inclusion_fk_in_pk=inclusion_fk_in_pk,
        inclusion_pk_in_fk=inclusion_pk_in_fk,
        derived=derived,
    ):
        return None
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
        return None
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
        "jaccard": _jaccard(fk_values, pk_values),
        "cardinality_alignment": _cardinality_alignment(
            fk_uniqueness=fk_sig.uniqueness_ratio,
            pk_uniqueness=pk_sig.uniqueness_ratio,
        ),
        "date_dimension_signal": date_dimension_signal,
        "spurious_guard": spurious_guard,
    }

    confidence = _weighted_score(signals=signals, weights=normalized_weights)
    confidence = min(confidence, date_cap)
    if derived is not None:
        confidence *= derived_conf_mult
    if confidence < min_confidence:
        return None

    return JoinCandidate(
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
            weights={key: float(value) for key, value in normalized_weights.items()},
            weighted_score=confidence,
        ),
        derived=derived,
    )


def _candidate_sort_key(candidate: JoinCandidate) -> tuple[float, str, str, str, str]:
    return (
        candidate.confidence,
        candidate.left_table.lower(),
        candidate.left_column.lower(),
        candidate.right_table.lower(),
        candidate.right_column.lower(),
    )


def _should_replace_candidate(current: JoinCandidate, incoming: JoinCandidate) -> bool:
    confidence_margin = incoming.confidence - current.confidence
    if confidence_margin > 1e-12:
        return True
    if confidence_margin < -1e-12:
        return False
    if current.derived is not None and incoming.derived is None:
        return True
    if current.derived is None and incoming.derived is not None:
        return False
    return _candidate_sort_key(incoming) > _candidate_sort_key(current)


def find_join_candidates(
    tables: list[Table],
    sample_rows: int = 10_000,
    min_confidence: float = 0.8,
    weights: dict[str, float] | None = None,
    sample_seed: int = 42,
    near_unique_threshold: float = DEFAULT_NEAR_UNIQUE_THRESHOLD,
    distinct_low_card_threshold: int = DEFAULT_DISTINCT_LOW_CARD_THRESHOLD,
    date_caps: dict[str, float] | None = None,
    derived_joins_enabled: bool = DERIVED_JOINS_ENABLED,
    derived_max_transforms_per_column: int = DERIVED_MAX_TRANSFORMS_PER_COLUMN,
    derived_max_columns_per_table: int = DERIVED_MAX_COLUMNS_PER_TABLE,
    derived_min_distinct: int = DERIVED_MIN_DISTINCT,
    derived_max_ambiguous_targets: int = DERIVED_MAX_AMBIGUOUS_TARGETS,
    derived_conf_mult: float = DERIVED_CONF_MULT,
    signature_cache: SignatureCache | None = None,
) -> list[JoinCandidate]:
    """Find join candidates using cached column signatures."""
    normalized_weights = _normalize_weights(weights)
    effective_derived_conf_mult = max(0.0, min(1.0, float(derived_conf_mult)))
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
    derived_budgets = DerivedBudgets(
        max_transforms_per_column=max(1, int(derived_max_transforms_per_column)),
        max_columns_per_table=max(1, int(derived_max_columns_per_table)),
        min_distinct=max(1, int(derived_min_distinct)),
    )
    derived_cache: dict[tuple[str, str], list[DerivedCandidate]] = {}
    derived_attempted: set[tuple[str, str]] = set()
    derived_rank_index: dict[tuple[str, str], int] = {}
    target_prefix_cache: dict[tuple[str, str], str | None] = {}
    if derived_joins_enabled:
        max_columns_per_table = max(0, int(derived_budgets.max_columns_per_table))
        for table in tables:
            table_sigs = [signatures[(table.name, column)] for column in table.df.columns]
            ranked_sources = rank_derived_source_columns(
                signatures=table_sigs,
                budgets=derived_budgets,
            )
            for rank, signature in enumerate(ranked_sources):
                source_key = (signature.table_name, signature.column_name)
                derived_rank_index[source_key] = rank
                if rank >= max_columns_per_table:
                    continue
                variants = derive_candidates_for_column(
                    signature=signature,
                    table_df=table.df,
                    sample_rows=sample_rows,
                    sample_seed=sample_seed,
                    budgets=derived_budgets,
                )
                derived_attempted.add(source_key)
                if variants:
                    derived_cache[source_key] = variants
    best_candidates: dict[tuple[str, str, str, str], JoinCandidate] = {}

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
                allow_direct = type_score > 0.0

                pair_candidates: list[JoinCandidate] = []
                overlap = left_sig.sampled_unique_set & right_sig.sampled_unique_set
                if allow_direct and overlap:
                    inclusion_lr = _estimated_inclusion(left_sig, right_sig)
                    inclusion_rl = _estimated_inclusion(right_sig, left_sig)
                    fk_sig, pk_sig, inclusion_fk_in_pk, inclusion_pk_in_fk = _normalize_direction(
                        left=left_sig,
                        right=right_sig,
                        inclusion_lr=inclusion_lr,
                        inclusion_rl=inclusion_rl,
                    )
                    fk_values = (
                        left_sig.sampled_unique_set
                        if fk_sig.table_name == left_sig.table_name
                        and fk_sig.column_name == left_sig.column_name
                        else right_sig.sampled_unique_set
                    )
                    pk_values = (
                        right_sig.sampled_unique_set
                        if pk_sig.table_name == right_sig.table_name
                        and pk_sig.column_name == right_sig.column_name
                        else left_sig.sampled_unique_set
                    )
                    direct_candidate = _score_candidate(
                        fk_sig=fk_sig,
                        pk_sig=pk_sig,
                        fk_values=fk_values,
                        pk_values=pk_values,
                        inclusion_fk_in_pk=inclusion_fk_in_pk,
                        inclusion_pk_in_fk=inclusion_pk_in_fk,
                        type_score=type_score,
                        normalized_weights=normalized_weights,
                        effective_date_caps=effective_date_caps,
                        min_confidence=min_confidence,
                        identifier_hubs=identifier_hubs,
                        table_identifier_winners=table_identifier_winners,
                        bridge_tables=bridge_tables,
                        mirror_pair=mirror_pair,
                        distinct_low_card_threshold=distinct_low_card_threshold,
                        derived_conf_mult=effective_derived_conf_mult,
                        derived=None,
                    )
                    if direct_candidate is not None:
                        pair_candidates.append(direct_candidate)

                name_similarity = _name_similarity(left_sig, right_sig)
                can_try_derived = (
                    bool(derived_rank_index)
                    and _derived_pair_prefilter(
                        left_sig=left_sig,
                        right_sig=right_sig,
                        name_similarity=name_similarity,
                    )
                )
                if can_try_derived:
                    left_variants = _get_or_build_derived_variants(
                        source_sig=left_sig,
                        target_sig=right_sig,
                        source_table=left_table,
                        sample_rows=sample_rows,
                        sample_seed=sample_seed,
                        budgets=derived_budgets,
                        derived_cache=derived_cache,
                        derived_attempted=derived_attempted,
                        derived_rank_index=derived_rank_index,
                        name_similarity=name_similarity,
                    )
                    for variant in left_variants:
                        if not _is_preferred_fk_direction(fk=left_sig, pk=right_sig):
                            continue
                        src_prefix = _dominant_prefix_from_values(
                            frozenset(variant.transformed_values_sample_set)
                        )
                        target_key = (right_sig.table_name, right_sig.column_name)
                        if target_key not in target_prefix_cache:
                            target_prefix_cache[target_key] = _dominant_prefix_from_values(
                                right_sig.sampled_unique_set
                            )
                        tgt_prefix = target_prefix_cache[target_key]
                        if (
                            src_prefix
                            and tgt_prefix
                            and _value_prefix_similarity(src_prefix, tgt_prefix) < 0.6
                        ):
                            continue
                        fk_values = _normalize_transformed_values_for_target(
                            transformed_values=variant.transformed_values_sample_set,
                            target_sig=right_sig,
                        )
                        if not (fk_values & right_sig.sampled_unique_set):
                            continue
                        if _derived_is_ambiguous(
                            transformed_fk_values=variant.transformed_values_sample_set,
                            target_table=right_table,
                            target_column=right_sig.column_name,
                            signatures=signatures,
                            max_ambiguous_targets=max(0, int(derived_max_ambiguous_targets)),
                            min_distinct=derived_budgets.min_distinct,
                        ):
                            continue
                        inclusion_fk_in_pk = _estimated_inclusion_from_sets(
                            left_set=fk_values,
                            right_set=right_sig.sampled_unique_set,
                            right_distinct_count=right_sig.distinct_count,
                        )
                        inclusion_pk_in_fk = _estimated_inclusion_from_sets(
                            left_set=right_sig.sampled_unique_set,
                            right_set=fk_values,
                            right_distinct_count=max(len(fk_values), 1),
                        )
                        derived_meta = DerivedTransform(
                            transform_id=variant.transform_id,
                            params=dict(variant.params),
                            description=transform_description(
                                transform_id=variant.transform_id,
                                params=variant.params,
                            ),
                            derived_from_table=left_sig.table_name,
                            derived_from_column=left_sig.column_name,
                            example_mappings=variant.example_mappings[:3],
                        )
                        derived_candidate = _score_candidate(
                            fk_sig=left_sig,
                            pk_sig=right_sig,
                            fk_values=fk_values,
                            pk_values=right_sig.sampled_unique_set,
                            inclusion_fk_in_pk=inclusion_fk_in_pk,
                            inclusion_pk_in_fk=inclusion_pk_in_fk,
                            type_score=type_score,
                            normalized_weights=normalized_weights,
                            effective_date_caps=effective_date_caps,
                            min_confidence=min_confidence,
                            identifier_hubs=identifier_hubs,
                            table_identifier_winners=table_identifier_winners,
                            bridge_tables=bridge_tables,
                            mirror_pair=mirror_pair,
                            distinct_low_card_threshold=distinct_low_card_threshold,
                            derived_conf_mult=effective_derived_conf_mult,
                            derived=derived_meta,
                        )
                        if derived_candidate is not None:
                            pair_candidates.append(derived_candidate)

                    right_variants = _get_or_build_derived_variants(
                        source_sig=right_sig,
                        target_sig=left_sig,
                        source_table=right_table,
                        sample_rows=sample_rows,
                        sample_seed=sample_seed,
                        budgets=derived_budgets,
                        derived_cache=derived_cache,
                        derived_attempted=derived_attempted,
                        derived_rank_index=derived_rank_index,
                        name_similarity=name_similarity,
                    )
                    for variant in right_variants:
                        if not _is_preferred_fk_direction(fk=right_sig, pk=left_sig):
                            continue
                        src_prefix = _dominant_prefix_from_values(
                            frozenset(variant.transformed_values_sample_set)
                        )
                        target_key = (left_sig.table_name, left_sig.column_name)
                        if target_key not in target_prefix_cache:
                            target_prefix_cache[target_key] = _dominant_prefix_from_values(
                                left_sig.sampled_unique_set
                            )
                        tgt_prefix = target_prefix_cache[target_key]
                        if (
                            src_prefix
                            and tgt_prefix
                            and _value_prefix_similarity(src_prefix, tgt_prefix) < 0.6
                        ):
                            continue
                        fk_values = _normalize_transformed_values_for_target(
                            transformed_values=variant.transformed_values_sample_set,
                            target_sig=left_sig,
                        )
                        if not (fk_values & left_sig.sampled_unique_set):
                            continue
                        if _derived_is_ambiguous(
                            transformed_fk_values=variant.transformed_values_sample_set,
                            target_table=left_table,
                            target_column=left_sig.column_name,
                            signatures=signatures,
                            max_ambiguous_targets=max(0, int(derived_max_ambiguous_targets)),
                            min_distinct=derived_budgets.min_distinct,
                        ):
                            continue
                        inclusion_fk_in_pk = _estimated_inclusion_from_sets(
                            left_set=fk_values,
                            right_set=left_sig.sampled_unique_set,
                            right_distinct_count=left_sig.distinct_count,
                        )
                        inclusion_pk_in_fk = _estimated_inclusion_from_sets(
                            left_set=left_sig.sampled_unique_set,
                            right_set=fk_values,
                            right_distinct_count=max(len(fk_values), 1),
                        )
                        derived_meta = DerivedTransform(
                            transform_id=variant.transform_id,
                            params=dict(variant.params),
                            description=transform_description(
                                transform_id=variant.transform_id,
                                params=variant.params,
                            ),
                            derived_from_table=right_sig.table_name,
                            derived_from_column=right_sig.column_name,
                            example_mappings=variant.example_mappings[:3],
                        )
                        derived_candidate = _score_candidate(
                            fk_sig=right_sig,
                            pk_sig=left_sig,
                            fk_values=fk_values,
                            pk_values=left_sig.sampled_unique_set,
                            inclusion_fk_in_pk=inclusion_fk_in_pk,
                            inclusion_pk_in_fk=inclusion_pk_in_fk,
                            type_score=type_score,
                            normalized_weights=normalized_weights,
                            effective_date_caps=effective_date_caps,
                            min_confidence=min_confidence,
                            identifier_hubs=identifier_hubs,
                            table_identifier_winners=table_identifier_winners,
                            bridge_tables=bridge_tables,
                            mirror_pair=mirror_pair,
                            distinct_low_card_threshold=distinct_low_card_threshold,
                            derived_conf_mult=effective_derived_conf_mult,
                            derived=derived_meta,
                        )
                        if derived_candidate is not None:
                            pair_candidates.append(derived_candidate)

                for candidate in pair_candidates:
                    key = (
                        candidate.left_table,
                        candidate.left_column,
                        candidate.right_table,
                        candidate.right_column,
                    )
                    current = best_candidates.get(key)
                    if current is None or _should_replace_candidate(current=current, incoming=candidate):
                        best_candidates[key] = candidate

    final_candidates = _dedupe_temporal_equivalent_targets(
        candidates=list(best_candidates.values()),
        signatures=signatures,
    )
    final_candidates = _dedupe_bidirectional_endpoint_pairs(final_candidates)
    final_candidates = _drop_dominated_noncanonical_targets(
        candidates=final_candidates,
        signatures=signatures,
        table_identifier_winners=table_identifier_winners,
    )
    final_candidates = _drop_noncanonical_alias_edges(
        candidates=final_candidates,
        signatures=signatures,
        table_identifier_winners=table_identifier_winners,
    )
    return sorted(
        final_candidates,
        key=lambda candidate: (
            -candidate.confidence,
            candidate.left_table.lower(),
            candidate.left_column.lower(),
            candidate.right_table.lower(),
            candidate.right_column.lower(),
        ),
    )
