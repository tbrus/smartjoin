# Test Datasets Generators

This folder contains **deterministic synthethic datasets generators used for smartjoin testing**.

## Quickstart

```
smartjoin generate-test-datasets --output-dir <output-dir>
```

## Output

```
<output-dir>
    generation_manifest.json      # generation config: domains, output paths, seed, profiles
    retail/                       # order-centric data with customers, products, orders, payments, shipments, etc.
    health/                       # healthcare-style data with patients, providers, facilities, payers, etc.
    saas/                         # subscription and billing-style data with accounts, users, workspaces, invoices, etc.
    derived/                      # focused derived-key testing scenario
```

Each domain writes a `manifest.json` describing:
- generator/config used
- row counts
- expected joins
- trap columns
- ground-truth relationships

The generated tables may be written in mixed formats: `.csv`, `.json`, `.parquet`, `.xlsx`.

## Common General Flags

- `--domain retail|health|saas`
- `--output-dir PATH`
- `--seed INT`
- `--profile tiny|small|medium|large`
- `--clean`

## Common Data Quality Flags
- `--pct-missing FLOAT`
- `--pct-duplicates FLOAT`
- `--pct-dirty-keys FLOAT`
- `--pct-derived-keys FLOAT`
- `--pct-derived-both-sides FLOAT`
- `--pct-inconsistent-types FLOAT`

## Notes
- `manifest.json` exposes core relationships and trap columns enabling accuracy checks
- data quality flags help creating "more difficult" datasets to analyze
