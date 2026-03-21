# Contributing

Thank you for considering contributing to smartjoin.

**smartjoin** is built with a specific goal and direction. Before contributing, please make sure your proposed change is aligned with the purpose of the package and keeps the project focused, maintainable, and useful.

## Before you contribute

Please:

- read the README to understand the current scope of the package
- check whether a similar issue or pull request already exists
- keep changes focused and easy to review
- make sure contributions are aligned with the goals of the project

For larger changes, opening an issue first is recommended.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
pre-commit install --hook-type pre-push
```

On Windows PowerShell:

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pre-commit install
pre-commit install --hook-type pre-push
```

## Running tests and checks

Before opening a pull request, please run:

```bash
pytest
ruff check .
ruff format --check .
```

If formatting changes are needed, run:

```bash
ruff format .
```

You can also run all configured hooks manually:

```bash
pre-commit run --all-files
```

## Pull requests

Please keep pull requests focused and easy to review.

If your change affects behavior, please:

- add or update tests
- update documentation if needed
- clearly describe what changed and why

## License

By contributing to smartjoin, you agree that your contributions will be licensed under the same license as the project.