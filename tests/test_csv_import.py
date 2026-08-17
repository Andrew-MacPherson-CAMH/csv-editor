"""Unit tests for core.csv_import's column-check and whole-file validation.

Run with:  python -m pytest tests/ -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from core.config import load_config
from core.csv_import import extra_columns, missing_columns, validate_dataframe
from core.validation import errors_only, warnings_only

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = {c.name: c for c in load_config(os.path.join(ROOT, "config.yaml")).columns}
EXPECTED = list(RULES.keys())


def test_missing_columns_reports_only_whats_absent():
    got = [c for c in EXPECTED if c != "latitude" and c != "longitude"]
    missing = missing_columns(got, EXPECTED)
    assert missing == ["latitude", "longitude"]   # preserves expected order


def test_missing_columns_empty_when_all_present():
    assert missing_columns(EXPECTED, EXPECTED) == []


def test_extra_columns_reports_unexpected_names():
    got = EXPECTED + ["some_extra_column"]
    assert extra_columns(got, EXPECTED) == ["some_extra_column"]


def test_extra_columns_empty_when_nothing_unexpected():
    assert extra_columns(EXPECTED, EXPECTED) == []


def _valid_row() -> dict:
    return {
        "service_category": "Crisis Lines: National",
        "name": "Test Line",
        "address": "",
        "city_town": "Ottawa",
        "province_territory": "Ontario",
        "postal_code": "",
        "phone_1": "911",
        "phone_2": "",
        "phone_3": "",
        "website": "https://example.com",
        "coverage_area": "",
        "hours_call": "",
        "hours_sms": "",
        "hours_chat": "",
        "description": "",
        "latitude": "45.0",
        "longitude": "-75.0",
    }


def test_validate_dataframe_all_valid_rows_have_no_errors():
    df = pd.DataFrame([_valid_row(), _valid_row()])
    findings = validate_dataframe(df, RULES)
    assert errors_only(findings) == {}


def test_validate_dataframe_catches_a_bad_cell_in_any_row_not_just_the_first():
    rows = [_valid_row(), _valid_row(), _valid_row()]
    rows[2]["postal_code"] = "12345"   # invalid format
    df = pd.DataFrame(rows)
    findings = validate_dataframe(df, RULES)
    errors = errors_only(findings)
    assert (2, "postal_code") in errors
    assert len(errors) == 1   # the other two rows are untouched


def test_validate_dataframe_flags_required_blank_as_warning_not_error():
    rows = [_valid_row()]
    rows[0]["phone_1"] = ""   # required, but blank is a warning, not an error
    df = pd.DataFrame(rows)
    findings = validate_dataframe(df, RULES)
    assert errors_only(findings) == {}
    assert (0, "phone_1") in warnings_only(findings)


def test_validate_dataframe_out_of_range_float_is_an_error():
    rows = [_valid_row()]
    rows[0]["latitude"] = "999"
    df = pd.DataFrame(rows)
    findings = validate_dataframe(df, RULES)
    assert (0, "latitude") in errors_only(findings)
