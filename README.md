<h1 align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/tbrus/smartjoin/main/docs/logo-dark-v1.png" height="42">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/tbrus/smartjoin/main/docs/logo-light-v1.png" height="42">
    <img src="https://raw.githubusercontent.com/tbrus/smartjoin/main/docs/logo-v1.png" height="42">
  </picture>
</h1>
<p align="center"><em>Stop guessing how your tables connect</em></p>

<span align="center">

[![License](https://img.shields.io/github/license/tbrus/smartjoin)](https://github.com/tbrus/smartjoin)
[![PyPI](https://img.shields.io/pypi/v/smartjoin-py)](https://pypi.org/project/smartjoin-py/)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![CI](https://github.com/tbrus/smartjoin/actions/workflows/ci.yml/badge.svg)](https://github.com/tbrus/smartjoin/actions/workflows/ci.yml)
[![Code style: Ruff](https://img.shields.io/badge/code%20style-Ruff-0F172A?logo=ruff&logoColor=white)](https://github.com/astral-sh/ruff)
![Formats: CSV, XLSX, JSON, Parquet](https://img.shields.io/badge/Formats-CSV%20%7C%20XLSX%20%7C%20JSON%20%7C%20Parquet-3FAF6C)

</span>

---

**smartjoin** helps you understand how unfamiliar datasets fit together — without schema docs, manual SQL detective work, or opaque guesses.

It scans structured data, profiles columns, discovers likely keys, infers candidate joins, and generates an interactive explorer so you can inspect the results.

Supports `.csv`, `.xlsx`, `.json`, `.parquet` input files.

<span align="center">
  <img src="https://raw.githubusercontent.com/tbrus/smartjoin/main/docs/explorer_preview.png">
</span>

## Example

Given a folder like:

- `orders.csv`
- `customers.xlsx`
- `payments.parquet`
- `shipments.json`

smartjoin can infer relationships such as:

| Source                | Target            | Type          | Confidence  | Origin     |
| --------------------- | ----------------- | ------------- | ----------- | ---------- |
| `orders.customer_id`  | `customers.id`    | `many_to_one` | `98%`       | `Direct`   |
| `payments.order_id`   | `orders.order_id` | `many_to_one` | `95%`       | `Derived`  |
| `shipments.order_ref` | `orders.order_id` | `one_to_one`  | `89%`       | `Direct`   |

## Quickstart

### Installation

```bash
pip install smartjoin-py
```

### Run

```bash
smartjoin run <path> <out_dir>
```

This analyzes the structured datasets in `<path>` and writes results to `<out_dir>`.

### Outputs

- `report.json` — full structured analysis output
- `relationships.csv` — flat table of discovered joins and scoring signals
- `explorer/index.html` — interactive explorer UI
- `explorer/data.json` — explorer payload

## Generate demo datasets

To explore smartjoin on deterministic synthetic data:

```bash
smartjoin generate-test-datasets --output-dir <output-dir>
```

## Limitations

smartjoin identifies **candidate relationships** across structured datasets. It **does not** guarantee semantic correctness.

Always review inferred joins before using them downstream. Domain meaning may still require human interpretation, and output quality depends on the structure and consistency of the input data.

## Roadmap

Future development may include:

- stronger semantic matching across columns and tables
- optional AI-assisted reasoning and scoring
- improved explorer and debugging capabilities
- broader support for real-world edge cases and heterogeneous datasets

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).


## License

Licensed under the [MIT License](LICENSE)