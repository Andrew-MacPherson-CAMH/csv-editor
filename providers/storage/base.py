from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

ROW_ID = "_row_id"
EditMap = dict[tuple[Any, str], Any]


class StorageError(Exception):
    pass


class StorageProvider(ABC):
    name: str = "base"

    audit_before_data_write: bool = False

    supports_import: bool = False

    def __init__(self, settings: dict[str, Any]):
        self.settings = settings

    @abstractmethod
    def load(self) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def apply_edits(self, df: pd.DataFrame, edits: EditMap) -> None:
        raise NotImplementedError

    def replace_all(self, new_df: pd.DataFrame) -> None:
        raise StorageError(f"{self.name} does not support replacing the whole dataset")

    def write_audit(
        self, metadata: dict[str, Any], records: list[dict[str, Any]]
    ) -> None:
        pass

    def display_name(self) -> str:
        return self.name
