# Alchemia

Alchemia is a deterministic, CLI-first relational inference engine for structured data folders.

V1 focuses on a practical vertical slice:
- discover and read CSV/Parquet/XLSX/JSON files from a folder,
- profile columns and tables (null/unique/entropy/duplicate stats),
- infer key candidates (single + bounded composite),
- infer weighted join candidates with explainable signal breakdown,
- build a join graph and export SQL skeleton.

## Why

Data engineers need inspectable and reproducible structure discovery before modeling. Alchemia emphasizes:
- deterministic outputs,
- explainable confidence scoring with signal breakdown,
- conservative defaults (precision over recall),
- clean architecture and testability.

## Quickstart

```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -e ".[dev]"
```

Analyze a folder of CSV files:

```bash
alchemia analyze ./data --format json --out report.json
```

Tune behavior:

```bash
alchemia analyze ./data --sample-rows 5000 --max-tables 10 --max-columns 40 --min-confidence 0.8
```

Build only join graph:

```bash
alchemia graph ./data --min-confidence 0.8 --out graph.json
```

Export SQL skeleton:

```bash
alchemia export-sql ./data --out schema.sql
```

Generate static debug website (separate from core outputs):

```bash
alchemia debug-site ./data --out-dir perf_outputs/debug_local
```

Then open `perf_outputs/debug_local/index.html` in your browser. The viewer includes:
- relationship canvas with table boxes, columns, and connection lines,
- confidence filtering slider,
- table sample preview mode.

Optional semantics plugin (disabled by default):

```bash
alchemia analyze ./data --llm --llm-plugin your_module:rerank_join_candidates
```

## Generate Performance Test Data

Generate deterministic, realistic join-heavy CSV datasets:

```bash
python scripts/generate_alchemia_testdata.py --profile small
python scripts/generate_alchemia_testdata.py --profile medium
python scripts/generate_alchemia_testdata.py --profile large
```

Generate a different-domain dataset (healthcare/claims schema):

```bash
python scripts/generate_alchemia_health_testdata.py --profile small
python scripts/generate_alchemia_health_testdata.py --profile medium
```

Generate a third domain dataset (B2B SaaS billing/events schema):

```bash
python scripts/generate_alchemia_saas_testdata.py --profile small
python scripts/generate_alchemia_saas_testdata.py --profile medium
```

Then analyze:

```bash
alchemia analyze perf_data/datasets/alchemia_medium --format json --out perf_outputs/alchemia_medium/report.json
alchemia debug-site perf_data/datasets/alchemia_medium --out-dir perf_outputs/alchemia_medium/html
```

Generate a broader generalization/performance suite (multiple scenarios + evaluation):

```bash
python scripts/generate_perf_suite.py
```

This creates:
- datasets in `perf_data/datasets/<scenario_name>/`
- outputs in `perf_outputs/<scenario_name>/` (`report.json`, `html/index.html`, `html/data.json`)
- suite summary in `perf_outputs/suite_summary.json`

The summary includes:
- generation/analysis timings,
- expected/predicted/missing/unexpected join counts,
- precision/recall/F1 against each scenario manifest.

Each generated dataset includes:
- multi-hop FK-like joins across 9+ tables,
- dirty key variants (whitespace, case, zero-padding),
- low-cardinality trap columns (`country`, `status`, `currency`, `region_code`),
- structured ground truth in `manifest.json` (`ground_truth.core_relationships`, `ground_truth.traps`),
- human-readable relationship/trap summary in dataset `README.md`.

`analyze`/`graph` automatically ignore metadata JSON stems (`manifest*`, `report*`, `graph*`) when scanning directories.

## Example JSON Output

```json
{
  "source_path": "C:/datasets/shop",
  "tables": [
    {
      "table_name": "customers",
      "row_count": 4,
      "columns": [
        {
          "name": "customer_id",
          "dtype": "Int64",
          "null_pct": 0.0,
          "distinct_count": 4,
          "sample_values": [1, 2, 3, 4]
        }
      ]
    }
  ],
  "joins": [
    {
      "left_table": "orders",
      "left_column": "customer_id",
      "right_table": "customers",
      "right_column": "customer_id",
      "confidence": 1.0,
      "breakdown": {
        "inclusion_ratio_left_in_right": 1.0,
        "inclusion_ratio_right_in_left": 0.75,
        "overlap_count": 3,
        "sampled_distinct_left": 3,
        "sampled_distinct_right": 4
      }
    }
  ]
}
```

## Roadmap

1. Improve type coercion and cross-format canonicalization.
2. Add stronger key pruning and large-table composite search strategies.
3. Add advanced spurious-join guards and configurable rule packs.
4. Add richer SQL export (FK constraints + dialect presets).
5. Add optional LLM-powered semantics plugin examples.

## Contributing

1. Fork and create a feature branch.
2. Keep logic deterministic and pure where possible.
3. Add tests for new behavior.
4. Run checks:

```bash
pytest
ruff check .
black --check .
```

5. Open a PR with motivation, implementation notes, and before/after behavior.
