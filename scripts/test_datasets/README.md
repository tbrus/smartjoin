# Test Dataset Generators

This folder contains generation-only dataset builders used for Smartjoin testing.

## Structure

- `run.py`: unified CLI for generating one domain or all domains
- `common/`: shared helper utilities and constants
- `domains/retail.py`: retail/order-centric generator
- `domains/health.py`: healthcare claims/encounters generator
- `domains/saas.py`: SaaS billing/events generator

## Quick Start

```bash
python scripts/test_datasets/run.py --output-dir test_datasets
python scripts/test_datasets/run.py --domain retail --output-dir test_datasets
python scripts/test_datasets/run.py --domain saas --seed 42 --output-dir test_datasets
smartjoin generate-test-datasets --output-dir test_datasets
smartjoin generate-test-datasets --domain retail --output-dir test_datasets
```

Outputs are written under `<output-dir>/<domain>/`.

## Domain-Specific Flags

`run.py` supports domain-specific flags by forwarding unknown arguments to the selected domain
generator. This only works with `--domain`.

Example:

```bash
python scripts/test_datasets/run.py --domain retail --profile tiny --n-orders 500 --output-dir test_datasets
```

Common derived-key mixing flags:

- `--pct-derived-keys` (default: `0.2`): fraction of join-key values emitted in derived form on one side
- `--pct-derived-both-sides` (default: `0.1`): fraction of selected relationships emitted in different derived forms on both sides

## Notes

- Generation only: no Smartjoin analysis, evaluation scoring, or debug site output.
- Deterministic behavior is preserved via explicit seeds.
- Each domain writes `manifest.json` and `README.md` where relevant.
