"""Load and expose application configuration.

The config file drives provider selection (auth + storage) and the
column/validation spec, so swapping providers or updating validation
rules requires no code changes.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

CONFIG_ENV_VAR = "CSV_EDITOR_CONFIG"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


@dataclass(frozen=True)
class ColumnRule:
    """Validation + display spec for a single column."""

    name: str
    label: str
    type: str = "string"          # string | number | integer | date
    required: bool = False
    min: Optional[float] = None
    max: Optional[float] = None
    max_length: Optional[int] = None
    regex: Optional[str] = None
    regex_hint: Optional[str] = None
    align: str = "left"
    editable: bool = True

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ColumnRule":
        name = raw["name"]
        return cls(
            name=name,
            label=raw.get("label", name.upper()),
            type=raw.get("type", "string"),
            required=bool(raw.get("required", False)),
            min=raw.get("min"),
            max=raw.get("max"),
            max_length=raw.get("max_length"),
            regex=raw.get("regex"),
            regex_hint=raw.get("regex_hint"),
            align=raw.get("align", "left"),
            editable=bool(raw.get("editable", True)),
        )


@dataclass(frozen=True)
class AppConfig:
    raw: dict[str, Any] = field(default_factory=dict)

    # --- app ---
    @property
    def title(self) -> str:
        return self.raw.get("app", {}).get("title", "Data Editor")

    @property
    def subtitle(self) -> str:
        return self.raw.get("app", {}).get("subtitle", "sign in to edit the dataset")

    # --- providers ---
    @property
    def auth_provider_name(self) -> str:
        return self.raw.get("auth", {}).get("provider", "mock")

    def auth_settings(self, name: Optional[str] = None) -> dict[str, Any]:
        name = name or self.auth_provider_name
        return self.raw.get("auth", {}).get(name, {}) or {}

    @property
    def storage_provider_name(self) -> str:
        return self.raw.get("storage", {}).get("provider", "local_csv")

    def storage_settings(self, name: Optional[str] = None) -> dict[str, Any]:
        name = name or self.storage_provider_name
        return self.raw.get("storage", {}).get(name, {}) or {}

    # --- dataset ---
    @property
    def dataset_display_name(self) -> str:
        return self.raw.get("dataset", {}).get("display_name", "dataset")

    @property
    def columns(self) -> list[ColumnRule]:
        cols = self.raw.get("dataset", {}).get("columns", []) or []
        return [ColumnRule.from_dict(c) for c in cols]


def load_config(path: Optional[str | Path] = None) -> AppConfig:
    """Load config from `path`, $CSV_EDITOR_CONFIG, or the default file."""
    cfg_path = Path(path or os.environ.get(CONFIG_ENV_VAR, DEFAULT_CONFIG_PATH))
    with open(cfg_path, "r", encoding="utf-8") as fh:
        return AppConfig(raw=yaml.safe_load(fh) or {})
