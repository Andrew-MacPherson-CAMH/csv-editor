"""Per-cell validation against per-column rules (type / length / regex).

Rules come from config (`dataset.columns`), so the real column spec can
be dropped in later without touching this module.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from core.config import ColumnRule

_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y")


def _is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def validate_cell(value, rule: ColumnRule) -> Optional[str]:
    """Return an error message (matching the wireframe tone, e.g.
    'must be a number, 1–999') or None if the value is valid."""
    if _is_blank(value):
        return "value is required" if rule.required else None

    text = str(value).strip()

    if rule.type in ("number", "integer"):
        try:
            num = float(text)
            if rule.type == "integer" and not float(num).is_integer():
                raise ValueError
        except (TypeError, ValueError):
            return _range_message(rule)
        if (rule.min is not None and num < rule.min) or (
            rule.max is not None and num > rule.max
        ):
            return _range_message(rule)

    elif rule.type == "date":
        if not _parse_date(text):
            return "not a valid date (YYYY-MM-DD)"

    if rule.max_length is not None and len(text) > rule.max_length:
        return f"too long (max {rule.max_length} characters)"

    if rule.regex is not None and re.fullmatch(rule.regex, text) is None:
        return rule.regex_hint or f"does not match required format (regex)"

    return None


def _range_message(rule: ColumnRule) -> str:
    kind = "a whole number" if rule.type == "integer" else "a number"
    if rule.min is not None and rule.max is not None:
        return f"must be {kind}, {_fmt(rule.min)}–{_fmt(rule.max)}"
    if rule.min is not None:
        return f"must be {kind} ≥ {_fmt(rule.min)}"
    if rule.max is not None:
        return f"must be {kind} ≤ {_fmt(rule.max)}"
    return f"must be {kind}"


def _fmt(n: float) -> str:
    return str(int(n)) if float(n).is_integer() else str(n)


def _parse_date(text: str) -> Optional[datetime]:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def validate_edits(
    edits: dict[tuple, str], rules_by_column: dict[str, ColumnRule]
) -> dict[tuple, str]:
    """Validate every pending edit. Returns {(row_id, column): error}."""
    errors: dict[tuple, str] = {}
    for (row_id, column), new_value in edits.items():
        rule = rules_by_column.get(column)
        if rule is None:
            continue
        err = validate_cell(new_value, rule)
        if err:
            errors[(row_id, column)] = err
    return errors
