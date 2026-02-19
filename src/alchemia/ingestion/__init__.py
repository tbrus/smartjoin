"""Ingestion module."""

from .loaders import discover_data_files, load_tables

__all__ = ["discover_data_files", "load_tables"]
