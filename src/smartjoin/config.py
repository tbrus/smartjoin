"""Central analysis settings and defaults."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_MIN_CONFIDENCE = 0.8
DEFAULT_TOP_K_EDGES = 3
DEFAULT_SAMPLE_ROWS = 10_000
DEFAULT_SAMPLE_SEED = 42
DEFAULT_DISTINCT_LOW_CARD_THRESHOLD = 64
DEFAULT_NEAR_UNIQUE_THRESHOLD = 0.90
DEFAULT_DATE_CAPS: dict[str, float] = {
    "temporal_overlap": 0.65,
    "mixed_temporal": 0.75,
    "temporal_overlap_signal": 0.35,
    "mixed_temporal_signal": 0.60,
}


def merge_date_caps(overrides: dict[str, float] | None = None) -> dict[str, float]:
    """Return date caps with defaults merged and values clamped to [0, 1]."""
    merged = dict(DEFAULT_DATE_CAPS)
    if overrides:
        for key, value in overrides.items():
            if key in merged:
                merged[key] = max(0.0, min(1.0, float(value)))
    return merged


@dataclass(frozen=True)
class AnalysisSettings:
    """Canonical runtime knobs for analysis and reporting."""

    min_confidence: float = DEFAULT_MIN_CONFIDENCE
    top_k_edges: int = DEFAULT_TOP_K_EDGES
    sample_rows: int = DEFAULT_SAMPLE_ROWS
    sample_seed: int = DEFAULT_SAMPLE_SEED
    distinct_low_card_threshold: int = DEFAULT_DISTINCT_LOW_CARD_THRESHOLD
    near_unique_threshold: float = DEFAULT_NEAR_UNIQUE_THRESHOLD
    date_caps: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_DATE_CAPS))

    def to_report_dict(self) -> dict[str, Any]:
        """Serialize as JSON-safe dict for `AnalysisReport.settings`."""
        return {
            "min_confidence": float(self.min_confidence),
            "top_k_edges": int(self.top_k_edges),
            "sample_rows": int(self.sample_rows),
            "sample_seed": int(self.sample_seed),
            "distinct_low_card_threshold": int(self.distinct_low_card_threshold),
            "near_unique_threshold": float(self.near_unique_threshold),
            "date_caps": {key: float(value) for key, value in self.date_caps.items()},
        }
