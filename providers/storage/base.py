"""Storage provider interface.

A provider loads the dataset into a pandas DataFrame and applies a set
of cell edits back to the underlying store.

Contract:
  * `load()` must return a DataFrame whose index is a stable, unique
    row id (`df.index.name == ROW_ID`). All edits are keyed by
    (row_id, column_name), so the id must survive filtering/sorting
    and round-trip to `apply_edits()`.
  * `apply_edits()` receives {(row_id, column): new_value} where every
    value has already passed validation, and must persist atomically
    where the backend allows it.

To add a provider:
  1. Subclass StorageProvider, implement load() + apply_edits().
  2. Register it in providers/storage/__init__.py.
  3. Point `storage.provider` at it in config.yaml.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

ROW_ID = "_row_id"
EditMap = dict[tuple[Any, str], Any]


class StorageError(Exception):
    """Raised when a storage backend cannot load or persist data."""


class StorageProvider(ABC):
    name: str = "base"

    def __init__(self, settings: dict[str, Any]):
        self.settings = settings

    @abstractmethod
    def load(self) -> pd.DataFrame:
        """Load the full dataset. Index = stable unique row id."""
        raise NotImplementedError

    @abstractmethod
    def apply_edits(self, df: pd.DataFrame, edits: EditMap) -> None:
        """Persist `edits` ({(row_id, column): new_value}) to the backend.

        `df` is the current in-memory dataset (original values), provided
        for backends that rewrite whole objects (e.g. a CSV file).
        """
        raise NotImplementedError

    def display_name(self) -> str:
        """Human-readable source name for the toolbar (override freely)."""
        return self.name
