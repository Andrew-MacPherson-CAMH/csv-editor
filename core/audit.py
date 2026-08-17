"""Change-log row builders — pure functions, no Streamlit/GCP imports.

The 988 change-log table has the same data columns as the dataset itself,
plus five metadata columns: change_id, change_state, change_type,
changed_by, changed_at. This module builds rows in exactly that shape;
StorageProvider.write_audit() just persists whatever it's given (see
providers/storage/base.py) — it doesn't interpret or require this shape,
so these helpers are the single source of truth for it.

Semantics:
  update  - TWO rows sharing one change_id: change_state "before" (the
            row's original values) and "after" (its new values).
  insert  - ONE row, change_state "after" only.
  delete  - ONE row, change_state "before" only. Built for schema
            completeness — there is no row-delete UI in this app, so
            nothing calls this yet.
"""
from __future__ import annotations

import uuid
from typing import Any, Mapping

import pandas as pd

from providers.storage.base import EditMap

CHANGE_STATE_BEFORE = "before"
CHANGE_STATE_AFTER = "after"
CHANGE_TYPE_INSERT = "insert"
CHANGE_TYPE_UPDATE = "update"
CHANGE_TYPE_DELETE = "delete"


def new_change_id() -> str:
    return f"CHG-{uuid.uuid4().hex[:8].upper()}"


def _snapshot(values: Mapping[str, Any], data_columns: list[str]) -> dict[str, Any]:
    """A flat {column: str(value)} snapshot over exactly `data_columns`,
    filling in "" for anything missing (defensive — callers should already
    have every column)."""
    return {col: "" if values.get(col) is None else str(values.get(col, "")) for col in data_columns}


def _row(
    values: Mapping[str, Any],
    data_columns: list[str],
    change_id: str,
    change_state: str,
    change_type: str,
    changed_by: str,
    changed_at: str,
) -> dict[str, Any]:
    return {
        **_snapshot(values, data_columns),
        "change_id": change_id,
        "change_state": change_state,
        "change_type": change_type,
        "changed_by": changed_by,
        "changed_at": changed_at,
    }


def update_rows(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    data_columns: list[str],
    changed_by: str,
    changed_at: str,
) -> list[dict[str, Any]]:
    """One change_id, two rows: the row's full snapshot before and after."""
    change_id = new_change_id()
    return [
        _row(before, data_columns, change_id, CHANGE_STATE_BEFORE, CHANGE_TYPE_UPDATE, changed_by, changed_at),
        _row(after, data_columns, change_id, CHANGE_STATE_AFTER, CHANGE_TYPE_UPDATE, changed_by, changed_at),
    ]


def insert_row(
    after: Mapping[str, Any], data_columns: list[str], changed_by: str, changed_at: str
) -> dict[str, Any]:
    return _row(
        after, data_columns, new_change_id(), CHANGE_STATE_AFTER, CHANGE_TYPE_INSERT, changed_by, changed_at
    )


def delete_row(
    before: Mapping[str, Any], data_columns: list[str], changed_by: str, changed_at: str
) -> dict[str, Any]:
    return _row(
        before, data_columns, new_change_id(), CHANGE_STATE_BEFORE, CHANGE_TYPE_DELETE, changed_by, changed_at
    )


def rows_for_edits(
    original_df: pd.DataFrame,
    edits: EditMap,
    data_columns: list[str],
    changed_by: str,
    changed_at: str,
) -> list[dict[str, Any]]:
    """Build change-log rows for a normal cell-edit publish.

    Edits are grouped by row_id FIRST: a row with 3 edited cells produces
    exactly one before/after pair (one change_id), not three.
    """
    by_row: dict[Any, dict[str, Any]] = {}
    for (row_id, column), value in edits.items():
        by_row.setdefault(row_id, {})[column] = value

    rows: list[dict[str, Any]] = []
    for row_id, patch in by_row.items():
        before = {col: original_df.at[row_id, col] for col in data_columns}
        after = {**before, **patch}
        rows.extend(update_rows(before, after, data_columns, changed_by, changed_at))
    return rows


def rows_for_full_replace(
    new_df: pd.DataFrame, data_columns: list[str], changed_by: str, changed_at: str
) -> list[dict[str, Any]]:
    """Build change-log rows for a full-dataset replace (CSV import) — one
    insert row per row in `new_df`, no before rows at all."""
    rows: list[dict[str, Any]] = []
    for _, row in new_df.iterrows():
        after = {col: row.get(col) for col in data_columns}
        rows.append(insert_row(after, data_columns, changed_by, changed_at))
    return rows
