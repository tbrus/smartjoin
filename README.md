<h1 align="center">
  <img src="https://raw.githubusercontent.com/tbrus/smartjoin/main/docs/logo.png" height="42" style="vertical-align: middle; margin-right: 10px;">
  <span style="vertical-align: middle;">smartjoin</span>
</h1>
<p align="center"><em>Data relationship discovery in seconds</em></p>

<p align="center">

[![License](https://img.shields.io/github/license/tbrus/smartjoin)](https://github.com/tbrus/smartjoin)
[![PyPI](https://img.shields.io/pypi/v/smartjoin-py)](https://pypi.org/project/smartjoin-py/)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![CI](https://github.com/tbrus/smartjoin/actions/workflows/ci.yml/badge.svg)](https://github.com/tbrus/smartjoin/actions/workflows/ci.yml)
[![Code style: Ruff](https://img.shields.io/badge/code%20style-Ruff-0F172A?logo=ruff&logoColor=white)](https://github.com/astral-sh/ruff)
![Formats: CSV, XLSX, JSON, Parquet](https://img.shields.io/badge/Formats-CSV%20%7C%20XLSX%20%7C%20JSON%20%7C%20Parquet-3FAF6C)

</p>

---
Stop guessing how your tables connect - **smartjoin automatically discovers relationships between structured datasets** — no schema, no docs, no manual SQL detective work.

When working with unfamiliar datasets, one of the hardest problems is understanding how files relate to each other.

smartjoin helps by **scanning** structured datasets, **identifying candidate relationships**, producing **explainable outputs** instead of opaque guesses and giving you an **explorer to inspect and review the results**.


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

### Generate test datasets

To explore how smartjoin works, you can generate synthethic test datasets:

```bash
smartjoin generate-test-datasets --output-dir <output-dir>
```

## Explorer

In addition to the output files, smartjoin generates an interactive HTML-based explorer that helps you inspect detected relationships visually.

<p align="center">
  <img src="https://raw.githubusercontent.com/tbrus/smartjoin/main/docs/explorer_preview.png">
</p>


## Limitations

smartjoin identifies candidate relationships across structured datasets. It **does not** guarantee semantic correctness.

Please keep in mind:

- inferred relationships should be reviewed before being relied on downstream
- domain-specific meaning may still require human interpretation
- output quality depends on the quality, consistency, and structure of the input data
- the tool is intended for structured dataset analysis, not as a general-purpose data processing platform

Currently supported input formats include: `.csv`, `.xlsx`, `.json`, `.parquet`.

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