# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Placeholder for upcoming features.

### Changed
- Placeholder for upcoming changes.

### Fixed
- Placeholder for upcoming fixes.

## [0.1.1] - 2026-03-22

### Changed
- Bundled test dataset generator scripts into the installed package so `smartjoin generate-test-datasets` works outside a source checkout.

### Fixed
- Fixed installed CLI error: `Test dataset generators are unavailable: scripts/test_datasets/run.py is missing.`
- Added loader fallback in CLI to use bundled dataset generators when source-tree scripts are not present.

## [0.1.0] - 2026-03-22

### Added
- Initial public release.
- Core relationship discovery engine for structured datasets.
- CLI commands for analysis (`smartjoin run`) and synthetic dataset generation (`smartjoin generate-test-datasets`).
- Explorer artifact generation for interactive output inspection.
- Support for loading CSV, Parquet, JSON, and XLSX data sources.