"""Deterministic derived-key transforms with strict anti-explosion budgets."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

import polars as pl

from smartjoin.joins.signatures import ColumnSignature

_QUALIFIER_TOKENS = {
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
_VALUE_PREFIX_MIN_SUPPORT = 0.6
_VALUE_PREFIX_MIN_SAMPLES = 20


@dataclass(frozen=True)
class TransformSpec:
    """One deterministic single-step transform."""

    id: str
    params: dict[str, Any]
    apply_fn: Callable[[str, dict[str, Any]], str | None]

    def apply(self, value: Any) -> str | None:
        text = _to_text(value)
        if text is None:
            return None
        return self.apply_fn(text, self.params)


@dataclass(frozen=True)
class DerivedCandidate:
    """Prepared derived values for one transform on one source column."""

    transform_id: str
    params: dict[str, Any]
    transformed_values_sample_set: frozenset[str]
    example_mappings: list[dict[str, str]]


@dataclass(frozen=True)
class DerivedBudgets:
    """Hard limits to bound derived-key search space."""

    max_transforms_per_column: int = 2
    max_columns_per_table: int = 6
    min_distinct: int = 20
    max_null_pct: float = 0.35
    max_variants_per_column: int = 3
    min_prefix_support: float = 0.7
    min_prefix_hits: int = 3

    def resolved_transform_cap(self) -> int:
        hard_cap = max(
            1, min(int(self.max_transforms_per_column), int(self.max_variants_per_column))
        )
        return hard_cap


def _stable_seed(sample_seed: int, table_name: str, column_name: str) -> int:
    payload = f"{sample_seed}|{table_name}|{column_name}|derived".encode()
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], byteorder="little", signed=False)


def _to_text(value: Any) -> str | None:
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    cleaned = text.strip()
    return cleaned or None


def _is_string_compatible_dtype(dtype: pl.DataType) -> bool:
    if dtype.is_temporal():
        return False
    if dtype == pl.Utf8 or dtype == pl.String or dtype == pl.Categorical:
        return True
    return dtype.is_numeric()


def is_derivation_eligible(signature: ColumnSignature, budgets: DerivedBudgets) -> bool:
    """Return whether a signature qualifies for transform derivation."""
    if not (signature.name_features.identifier_like or signature.name_features.code_like):
        return False
    if signature.name_features.date_like:
        return False
    if signature.dtype.is_temporal():
        return False
    if not _is_string_compatible_dtype(signature.dtype):
        return False
    if signature.distinct_count < budgets.min_distinct:
        return False
    if signature.row_count <= 0:
        return False
    null_pct = 1.0 - (signature.non_null_count / signature.row_count)
    return null_pct <= budgets.max_null_pct


def _sample_distinct_strings(
    series: pl.Series,
    table_name: str,
    column_name: str,
    sample_rows: int,
    sample_seed: int,
) -> list[str]:
    distinct = series.drop_nulls().unique(maintain_order=False)
    if distinct.len() == 0:
        return []
    n = min(sample_rows, distinct.len())
    sampled = distinct.sample(
        n=n,
        with_replacement=False,
        shuffle=True,
        seed=_stable_seed(sample_seed=sample_seed, table_name=table_name, column_name=column_name),
    )
    out: list[str] = []
    seen: set[str] = set()
    for value in sampled.to_list():
        text = _to_text(value)
        if text is None:
            continue
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _transform_strip_non_alnum(value: str, _params: dict[str, Any]) -> str | None:
    transformed = re.sub(r"[^A-Za-z0-9]", "", value)
    return transformed or None


def _transform_lowercase(value: str, _params: dict[str, Any]) -> str | None:
    transformed = value.lower()
    return transformed or None


def _transform_remove_prefix(value: str, params: dict[str, Any]) -> str | None:
    prefix = str(params.get("prefix", "")).strip()
    if not prefix:
        return value
    pattern = re.compile(rf"^{re.escape(prefix)}[-_\s]*", re.IGNORECASE)
    transformed = pattern.sub("", value, count=1)
    return transformed or None


def _transform_replace_prefix(value: str, params: dict[str, Any]) -> str | None:
    from_prefix = str(params.get("from", "")).strip()
    to_prefix = str(params.get("to", "")).strip()
    if not from_prefix:
        return value
    pattern = re.compile(rf"^{re.escape(from_prefix)}[-_\s]*", re.IGNORECASE)
    transformed = pattern.sub(to_prefix, value, count=1)
    return transformed or None


def _transform_strip_hyphens_underscores(value: str, _params: dict[str, Any]) -> str | None:
    transformed = re.sub(r"[-_]", "", value)
    return transformed or None


def transform_description(transform_id: str, params: dict[str, Any]) -> str:
    """Return a deterministic human-readable description for a transform."""
    normalized_id = str(transform_id or "").strip().lower()
    raw_params = params if isinstance(params, dict) else {}

    if normalized_id == "strip_non_alnum":
        return "Strip non-alphanumeric characters"
    if normalized_id == "lowercase":
        return "Convert to lowercase"
    if normalized_id == "strip_hyphens_underscores":
        return "Remove hyphens and underscores"
    if normalized_id == "remove_prefix":
        prefix = str(raw_params.get("prefix", "")).strip()
        if prefix:
            return f"Remove prefix '{prefix}'"
        return "Remove detected prefix"
    if normalized_id == "replace_prefix":
        from_prefix = str(raw_params.get("from", "")).strip()
        to_prefix = str(raw_params.get("to", "")).strip()
        if from_prefix or to_prefix:
            return f"Replace prefix '{from_prefix}' -> '{to_prefix}'"
        return "Replace detected prefix"

    label = normalized_id.replace("_", " ").strip()
    if label:
        label = label[0].upper() + label[1:]
    else:
        label = "Unknown transform"
    if raw_params:
        params_text = ", ".join(
            f"{key}={raw_params[key]!r}" for key in sorted(raw_params.keys(), key=str)
        )
        return f"{label} ({params_text})"
    return label


def _extract_prefix_token(value: str) -> str | None:
    match = re.match(r"^\s*([A-Za-z]{2,})", value)
    if not match:
        return None
    return match.group(1).lower()


def detect_dominant_value_prefix(
    values: list[str],
    min_support: float = _VALUE_PREFIX_MIN_SUPPORT,
    min_samples: int = _VALUE_PREFIX_MIN_SAMPLES,
) -> str | None:
    """
    Detect a dominant leading alpha prefix from sampled identifier-like values.

    Returns lowercased prefix token when:
    - at least `min_samples` values expose a leading alpha token
    - most common token support is at least `min_support`
    """
    if min_samples <= 0:
        min_samples = 1
    if min_support <= 0:
        min_support = 0.0

    prefixes: list[str] = []
    for raw in values:
        text = _to_text(raw)
        if text is None:
            continue
        match = re.match(r"^[A-Za-z]+", text)
        if not match:
            continue
        token = match.group(0).lower()
        if token:
            prefixes.append(token)

    if len(prefixes) < min_samples:
        return None
    counts: dict[str, int] = {}
    for token in prefixes:
        counts[token] = counts.get(token, 0) + 1
    dominant, count = max(counts.items(), key=lambda item: (item[1], item[0]))
    support = count / max(len(prefixes), 1)
    if support < min_support:
        return None
    return dominant


def _detect_dominant_prefix(
    sampled_values: list[str],
    budgets: DerivedBudgets,
) -> str | None:
    prefix_hits: list[str] = []
    for value in sampled_values:
        token = _extract_prefix_token(value)
        if token is None:
            continue
        prefix_hits.append(token)
    if len(prefix_hits) < budgets.min_prefix_hits:
        return None
    counts: dict[str, int] = {}
    for prefix in prefix_hits:
        counts[prefix] = counts.get(prefix, 0) + 1
    dominant_prefix = max(counts.items(), key=lambda item: (item[1], item[0]))
    support = dominant_prefix[1] / max(len(sampled_values), 1)
    if support < budgets.min_prefix_support:
        return None
    return dominant_prefix[0]


def _abbreviate_prefix(prefix: str) -> str | None:
    if len(prefix) <= 3:
        return None
    consonant_compact = prefix[0] + re.sub(r"[aeiou]", "", prefix[1:])
    if len(consonant_compact) >= 3 and consonant_compact != prefix:
        return consonant_compact
    fallback = prefix[:3]
    if fallback != prefix:
        return fallback
    return None


def _prefix_replacement_candidates(prefix: str) -> tuple[str, ...]:
    candidates: list[str] = []
    abbrev = _abbreviate_prefix(prefix)
    if abbrev:
        candidates.append(abbrev)
    if len(prefix) > 4:
        candidates.append(prefix[:4])
    if len(prefix) > 3:
        candidates.append(prefix[:3])
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        cleaned = candidate.strip().lower()
        if not cleaned or cleaned == prefix or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(cleaned)
    return tuple(deduped)


def _build_specs(
    dominant_prefix: str | None,
) -> list[TransformSpec]:
    specs: list[TransformSpec] = [
        TransformSpec(
            id="strip_non_alnum",
            params={},
            apply_fn=_transform_strip_non_alnum,
        ),
        TransformSpec(
            id="strip_hyphens_underscores",
            params={},
            apply_fn=_transform_strip_hyphens_underscores,
        ),
        TransformSpec(
            id="lowercase",
            params={},
            apply_fn=_transform_lowercase,
        ),
    ]
    if dominant_prefix:
        specs.insert(
            0,
            TransformSpec(
                id="remove_prefix",
                params={"prefix": dominant_prefix},
                apply_fn=_transform_remove_prefix,
            ),
        )
        for replacement in _prefix_replacement_candidates(dominant_prefix):
            specs.insert(
                0,
                TransformSpec(
                    id="replace_prefix",
                    params={"from": dominant_prefix, "to": replacement},
                    apply_fn=_transform_replace_prefix,
                ),
            )
    return specs


def normalize_transformed_value_for_signature(value: Any, signature: ColumnSignature) -> object:
    text = _to_text(value)
    if text is None:
        return ""
    if signature.dtype.is_numeric():
        numeric = re.fullmatch(r"[-+]?0*([0-9]+)", text)
        if numeric:
            return int(numeric.group(1))
        return text
    if signature.name_features.identifier_like or signature.name_features.code_like:
        upper = text.upper()
        match = re.fullmatch(r"0*([A-Z]+)[_\-\s]*0*([0-9]+)", upper)
        if match:
            prefix, digits = match.groups()
            return f"{prefix}{int(digits)}"
        numeric = re.fullmatch(r"0*([0-9]+)", upper)
        if numeric:
            return str(int(numeric.group(1)))
        return upper
    return text


def derive_candidates_for_column(
    signature: ColumnSignature,
    table_df: pl.DataFrame,
    sample_rows: int,
    sample_seed: int,
    budgets: DerivedBudgets,
) -> list[DerivedCandidate]:
    """Generate bounded deterministic transform variants for one column."""
    if not is_derivation_eligible(signature=signature, budgets=budgets):
        return []
    if signature.column_name not in table_df.columns:
        return []

    sampled_values = _sample_distinct_strings(
        series=table_df.get_column(signature.column_name),
        table_name=signature.table_name,
        column_name=signature.column_name,
        sample_rows=sample_rows,
        sample_seed=sample_seed,
    )
    if len(sampled_values) < budgets.min_prefix_hits:
        return []

    dominant_prefix = _detect_dominant_prefix(sampled_values=sampled_values, budgets=budgets)
    specs = _build_specs(dominant_prefix=dominant_prefix)
    cap = budgets.resolved_transform_cap()

    out: list[DerivedCandidate] = []
    seen_sets: set[frozenset[object]] = set()
    base_set = signature.sampled_unique_set
    min_changes = max(2, int(0.05 * len(sampled_values)))

    for spec in specs:
        transformed_values: set[str] = set()
        derived_values: set[object] = set()
        examples: list[dict[str, str]] = []
        changed = 0

        for raw in sampled_values:
            transformed = spec.apply(raw)
            if transformed is None:
                continue
            transformed_values.add(transformed)
            normalized = normalize_transformed_value_for_signature(
                transformed,
                signature=signature,
            )
            derived_values.add(normalized)
            if transformed != raw:
                changed += 1
                if len(examples) < 3:
                    examples.append({"from": raw, "to": transformed})

        if changed < min_changes:
            continue
        derived_set = frozenset(derived_values)
        if not derived_set or derived_set == base_set:
            continue
        if derived_set in seen_sets:
            continue
        seen_sets.add(derived_set)
        transformed_set = frozenset(transformed_values)
        out.append(
            DerivedCandidate(
                transform_id=spec.id,
                params=dict(spec.params),
                transformed_values_sample_set=transformed_set,
                example_mappings=examples[:3],
            )
        )
        if len(out) >= cap:
            break

    return out


def _core_tokens(signature: ColumnSignature) -> set[str]:
    def _canonical_token(token: str) -> str:
        normalized = re.sub(r"[^a-z0-9]", "", token.lower())
        if not normalized:
            return ""
        if normalized.endswith("ies") and len(normalized) > 3:
            return normalized[:-3] + "y"
        if normalized.endswith("s") and len(normalized) > 3:
            return normalized[:-1]
        return normalized

    raw_tokens: list[str] = []
    if signature.name_features.entity_core:
        raw_tokens.extend(re.findall(r"[a-z]+", signature.name_features.entity_core.lower()))
    if not raw_tokens:
        raw_tokens.extend(
            token for token in signature.name_features.tokens if token not in _QUALIFIER_TOKENS
        )
    canonical = {_canonical_token(token) for token in raw_tokens if token}
    return {token for token in canonical if token}


def entity_cores_compatible(left: ColumnSignature, right: ColumnSignature) -> bool:
    """
    Conservative namespace check used to reject derived joins across entities.

    If both sides expose a core namespace and there is no overlap, reject.
    """
    left_tokens = _core_tokens(left)
    right_tokens = _core_tokens(right)
    if not left_tokens or not right_tokens:
        return True
    if left_tokens & right_tokens:
        return True
    for left_token in left_tokens:
        for right_token in right_tokens:
            if min(len(left_token), len(right_token)) >= 3:
                if left_token.startswith(right_token) or right_token.startswith(left_token):
                    return True
                if SequenceMatcher(None, left_token, right_token).ratio() >= 0.72:
                    return True
    return False


def rank_derived_source_columns(
    signatures: list[ColumnSignature],
    budgets: DerivedBudgets,
) -> list[ColumnSignature]:
    """Order eligible source columns by identifier strength and cardinality."""
    eligible = [sig for sig in signatures if is_derivation_eligible(signature=sig, budgets=budgets)]

    def _score(sig: ColumnSignature) -> tuple[int, int, int, float, int, str]:
        return (
            int(sig.name_features.id_like),
            int(sig.name_features.key_like),
            int(sig.name_features.code_like),
            float(sig.uniqueness_ratio),
            int(sig.distinct_count),
            sig.column_name.lower(),
        )

    return sorted(eligible, key=_score, reverse=True)
