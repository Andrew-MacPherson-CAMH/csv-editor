"""Unit tests for core.audit's change-log row builders.

Run with:  python -m pytest tests/ -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from core.audit import (
    CHANGE_STATE_AFTER,
    CHANGE_STATE_BEFORE,
    CHANGE_TYPE_DELETE,
    CHANGE_TYPE_INSERT,
    CHANGE_TYPE_UPDATE,
    delete_row,
    insert_row,
    new_change_id,
    rows_for_edits,
    rows_for_full_replace,
    update_rows,
)

DATA_COLUMNS = ["name", "phone_1", "city_town"]


def test_new_change_id_shape_and_uniqueness():
    ids = {new_change_id() for _ in range(50)}
    assert len(ids) == 50
    assert all(cid.startswith("CHG-") and len(cid) == len("CHG-") + 8 for cid in ids)


def test_update_rows_pairs_before_and_after_with_one_change_id():
    before = {"name": "Old Name", "phone_1": "111", "city_town": "Ottawa"}
    after = {"name": "New Name", "phone_1": "111", "city_town": "Ottawa"}
    rows = update_rows(before, after, DATA_COLUMNS, "user@x.com", "2026-01-01T00:00:00+00:00")

    assert len(rows) == 2
    b, a = rows
    assert b["change_id"] == a["change_id"]
    assert b["change_state"] == CHANGE_STATE_BEFORE
    assert a["change_state"] == CHANGE_STATE_AFTER
    assert b["change_type"] == a["change_type"] == CHANGE_TYPE_UPDATE
    assert b["changed_by"] == a["changed_by"] == "user@x.com"
    assert b["name"] == "Old Name" and a["name"] == "New Name"
    assert b["phone_1"] == a["phone_1"] == "111"   # unchanged column still snapshotted


def test_update_rows_generates_a_fresh_change_id_each_call():
    before = {"name": "A", "phone_1": "1", "city_town": "X"}
    r1 = update_rows(before, before, DATA_COLUMNS, "u", "t")
    r2 = update_rows(before, before, DATA_COLUMNS, "u", "t")
    assert r1[0]["change_id"] != r2[0]["change_id"]


def test_insert_row_is_after_only():
    row = insert_row({"name": "New", "phone_1": "1", "city_town": "Y"}, DATA_COLUMNS, "u", "t")
    assert row["change_state"] == CHANGE_STATE_AFTER
    assert row["change_type"] == CHANGE_TYPE_INSERT


def test_delete_row_is_before_only():
    row = delete_row({"name": "Gone", "phone_1": "1", "city_town": "Z"}, DATA_COLUMNS, "u", "t")
    assert row["change_state"] == CHANGE_STATE_BEFORE
    assert row["change_type"] == CHANGE_TYPE_DELETE


def test_snapshot_missing_values_become_empty_string():
    row = insert_row({"name": "New"}, DATA_COLUMNS, "u", "t")   # phone_1/city_town absent
    assert row["phone_1"] == ""
    assert row["city_town"] == ""


def test_rows_for_edits_groups_multiple_cell_edits_on_one_row_into_one_pair():
    original = pd.DataFrame(
        {"name": ["Old Name"], "phone_1": ["111"], "city_town": ["Ottawa"]},
        index=pd.Index([7], name="_row_id"),
    )
    edits = {(7, "name"): "New Name", (7, "phone_1"): "222"}
    rows = rows_for_edits(original, edits, DATA_COLUMNS, "u@x.com", "t")

    assert len(rows) == 2   # ONE before/after pair, not two (3 edited cells would still be 2)
    before, after = rows
    assert before["change_id"] == after["change_id"]
    assert before["name"] == "Old Name" and after["name"] == "New Name"
    assert before["phone_1"] == "111" and after["phone_1"] == "222"
    assert before["city_town"] == after["city_town"] == "Ottawa"   # untouched column carried through


def test_rows_for_edits_produces_one_pair_per_distinct_row():
    original = pd.DataFrame(
        {"name": ["A", "B"], "phone_1": ["1", "2"], "city_town": ["X", "Y"]},
        index=pd.Index([0, 1], name="_row_id"),
    )
    edits = {(0, "name"): "A2", (1, "name"): "B2"}
    rows = rows_for_edits(original, edits, DATA_COLUMNS, "u", "t")
    change_ids = {r["change_id"] for r in rows}
    assert len(rows) == 4
    assert len(change_ids) == 2   # two separate rows -> two separate change_ids


def test_rows_for_full_replace_is_insert_only_no_before_rows():
    new_df = pd.DataFrame(
        {"name": ["A", "B"], "phone_1": ["1", "2"], "city_town": ["X", "Y"]}
    )
    rows = rows_for_full_replace(new_df, DATA_COLUMNS, "u", "t")
    assert len(rows) == 2   # one row per imported row, no before rows
    assert all(r["change_state"] == CHANGE_STATE_AFTER for r in rows)
    assert all(r["change_type"] == CHANGE_TYPE_INSERT for r in rows)
    change_ids = {r["change_id"] for r in rows}
    assert len(change_ids) == 2   # each insert gets its own change_id
