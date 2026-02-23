"""Optional plugin interface for semantic tie-breaking."""

from __future__ import annotations

import importlib
from collections.abc import Callable

from smartjoin.models import JoinCandidate

PluginFn = Callable[[list[JoinCandidate]], list[JoinCandidate]]


def default_semantic_tie_breaker(candidates: list[JoinCandidate]) -> list[JoinCandidate]:
    """
    Deterministic fallback semantic plugin.

    This does not require any model; it only applies a stable tie-break:
    prefer `_id`/`id`-like columns when confidence is equal.
    """
    return sorted(
        candidates,
        key=lambda candidate: (
            -candidate.confidence,
            0 if candidate.left_column.lower().endswith("id") else 1,
            0 if candidate.right_column.lower().endswith("id") else 1,
            candidate.left_table.lower(),
            candidate.right_table.lower(),
            candidate.left_column.lower(),
            candidate.right_column.lower(),
        ),
    )


def load_semantics_plugin(plugin_path: str | None) -> PluginFn:
    """Load plugin function from `module:function` path."""
    if not plugin_path:
        return default_semantic_tie_breaker

    if ":" not in plugin_path:
        raise ValueError("Plugin path must be in 'module:function' format.")

    module_name, function_name = plugin_path.split(":", maxsplit=1)
    module = importlib.import_module(module_name)
    plugin = getattr(module, function_name, None)
    if plugin is None or not callable(plugin):
        raise ValueError(f"Invalid semantics plugin function: {plugin_path}")
    return plugin


def apply_semantics_plugin(
    candidates: list[JoinCandidate],
    llm_enabled: bool = False,
    plugin_path: str | None = None,
) -> list[JoinCandidate]:
    """Conditionally apply semantics plugin to rerank join candidates."""
    if not llm_enabled:
        return candidates

    plugin = load_semantics_plugin(plugin_path)
    return plugin(candidates)
