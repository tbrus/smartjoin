"""Reusable generation helpers."""

from __future__ import annotations

import csv
import random
import re
import string
from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any


def idf(prefix: str, value: int, width: int) -> str:
    return f"{prefix}{value:0{width}d}"


def iso(base: date, offset: int) -> str:
    return (base + timedelta(days=offset)).isoformat()


def pick(rng: random.Random, values: Sequence[str], weights: Sequence[int]) -> str:
    return rng.choices(list(values), weights=list(weights), k=1)[0]


def maybe_missing(rng: random.Random, value: Any, probability: float) -> Any:
    return "" if rng.random() < probability else value


def dirty_key(rng: random.Random, value: str) -> str:
    mode = rng.random()
    if mode < 0.33:
        return f" {value} "
    if mode < 0.66:
        return value.lower()
    return value.zfill(len(value) + rng.randint(1, 3))


def token(rng: random.Random, n: int) -> str:
    return "".join(rng.choices(string.ascii_uppercase + string.digits, k=n))


def write_csv(path: Path, fields: list[str], rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def sample_lines(rng: random.Random, avg: float, max_lines: int = 12) -> int:
    p_stop = min(0.95, max(0.05, 1.0 / max(avg, 1.0)))
    count = 1
    while count < max_lines and rng.random() > p_stop:
        count += 1
    return count


def split_prefixed_numeric(value: str) -> tuple[str, str] | None:
    match = re.search(r"([A-Za-z]+)[^0-9]*([0-9]+)", value.strip())
    if match is None:
        return None
    return match.group(1), match.group(2)


def derive_prefixed_numeric(
    value: str,
    *,
    style: str,
    prefix_override: str | None = None,
) -> str:
    parts = split_prefixed_numeric(value)
    if parts is None:
        return value
    prefix, digits = parts
    prefix = prefix_override or prefix

    if style == "canonical":
        return f"{prefix.upper()}{digits}"
    if style == "dash_lower":
        return f"{prefix.lower()}-{digits}"
    if style == "underscore_upper":
        return f"{prefix.upper()}_{digits}"
    if style == "hash_lower":
        return f"{prefix.lower()}#{digits}"
    if style == "slash_lower":
        return f"{prefix.lower()}/{digits}"
    if style == "space_dash":
        return f" {prefix.lower()}-{digits} "
    raise ValueError(f"Unsupported derived style: {style}")
