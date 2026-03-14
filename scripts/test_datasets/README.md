# Test Dataset Generators

This folder contains generation-only dataset builders used for Smartjoin testing.

## Structure

- `run.py`: unified CLI for generating one domain or all domains
- `common/`: shared helper utilities and constants
- `domains/retail.py`: retail/order-centric generator
- `domains/health.py`: healthcare claims/encounters generator
- `domains/saas.py`: SaaS billing/events generator
- `domains/derived.py`: focused derived-key regression scenarios

## Quick Start

```bash
python scripts/test_datasets/run.py --output-dir test_datasets
python scripts/test_datasets/run.py --pct-derived-keys 0.5 --pct-derived-both-sides 0.25 --output-dir test_datasets
python scripts/test_datasets/run.py --domain retail --output-dir test_datasets
python scripts/test_datasets/run.py --domain derived --output-dir test_datasets
python scripts/test_datasets/run.py --domain saas --seed 42 --output-dir test_datasets
smartjoin generate-test-datasets --output-dir test_datasets
smartjoin generate-test-datasets --pct-derived-keys 0.5 --pct-derived-both-sides 0.25 --output-dir test_datasets
smartjoin generate-test-datasets --domain retail --output-dir test_datasets
smartjoin generate-test-datasets --domain derived --output-dir test_datasets
```

Outputs are written under `<output-dir>/<domain>/`, including `manifest.json` and generated input files.

## Explicit Common Flags

`run.py` now exposes common generation flags directly:

- `--profile`, `--seed`, `--clean`
- `--pct-missing`, `--pct-duplicates`, `--pct-dirty-keys`
- `--pct-derived-keys`, `--pct-derived-both-sides`
- `--pct-inconsistent-types`
- `--include-json`, `--max-json-records`

These common flags work with both:

- all domains (omit `--domain`)
- one selected domain (`--domain retail|health|saas|derived`)

Domain-specific size overrides are still supported by forwarding unknown flags when `--domain` is set.

Example:

```bash
python scripts/test_datasets/run.py --domain retail --profile tiny --n-orders 500 --output-dir test_datasets
```

## Notes

- Generation only: no Smartjoin analysis, evaluation scoring, or debug site output.
- Deterministic behavior is preserved via explicit seeds.
- Each domain writes `manifest.json`.
- Legacy per-domain `README.md` files are removed on generation.
- Manifest creation is centralized in `common/manifest.py` to avoid per-domain duplication.

## Manifest Schema

All domain manifests now share the same top-level shape:

- `generator`, `config`, `row_counts`
- `expected_joins`
- `trap_columns`
- `ground_truth`

`ground_truth` includes a normalized key set across domains:

- `core_tables`, `core_relationships`, `composite_key_candidates`, `traps`
- `guard_expectations`, `regression_cases`

Some fields are intentionally empty in domains where they do not apply.
