"""CSV import validation — pure functions, no Streamlit imports.

An imported CSV fully REPLACES the dataset, so it needs two checks before
it can be published: (1) it has exactly the right columns, (2) every cell
in the whole file passes the same per-cell rules the app already applies
everywhere else (core.validation) — not just a diff against what's there
today, since there's nothing meaningful to diff against for a fresh import.
"""
from __future__ import annotations

import pandas as pd

from core.config import ColumnRule
from core.validation import validate_cell


def missing_columns(got: list[str], expected: list[str]) -> list[str]:
    """Expected columns not present in `got`, in the expected display order."""
    got_set = set(got)
    return [c for c in expected if c not in got_set]


def extra_columns(got: list[str], expected: list[str]) -> list[str]:
    """Columns in `got` that aren't part of the expected schema, in file order."""
    expected_set = set(expected)
    return [c for c in got if c not in expected_set]


def validate_dataframe(
    df: pd.DataFrame, rules_by_column: dict[str, ColumnRule]
) -> dict[tuple, tuple[str, str]]:
    """Validate every cell of the whole dataframe.

    Same {(row_id, column): (severity, message)} shape as
    core.validation.validate_edits, so errors_only/warnings_only work on
    the result unmodified.
    """
    findings: dict[tuple, tuple[str, str]] = {}
    for row_id in df.index:
        for column, rule in rules_by_column.items():
            if column not in df.columns:
                continue
            finding = validate_cell(df.at[row_id, column], rule)
            if finding:
                findings[(row_id, column)] = finding
    return findings
