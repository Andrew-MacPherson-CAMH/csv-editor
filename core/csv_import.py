from __future__ import annotations

import pandas as pd

from core.config import ColumnRule
from core.validation import validate_cell


def missing_columns(got: list[str], expected: list[str]) -> list[str]:
    got_set = set(got)
    return [c for c in expected if c not in got_set]


def extra_columns(got: list[str], expected: list[str]) -> list[str]:
    expected_set = set(expected)
    return [c for c in got if c not in expected_set]


def validate_dataframe(
    df: pd.DataFrame, rules_by_column: dict[str, ColumnRule]
) -> dict[tuple, tuple[str, str]]:
    findings: dict[tuple, tuple[str, str]] = {}
    for row_id in df.index:
        for column, rule in rules_by_column.items():
            if column not in df.columns:
                continue
            finding = validate_cell(df.at[row_id, column], rule)
            if finding:
                findings[(row_id, column)] = finding
    return findings
