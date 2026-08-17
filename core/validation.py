from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from core.config import ColumnRule

ERROR = "error"
WARNING = "warning"

_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y")


def _is_blank(value) -> bool:
    return value is None or str(value).strip() == ""


def normalize_value(value, rule: ColumnRule) -> str:
    text = "" if value is None else str(value).strip()
    if rule.normalize == "postal_code" and text:
        compact = re.sub(r"\s+", "", text).upper()
        if len(compact) == 6:
            text = f"{compact[:3]} {compact[3:]}"
        else:
            text = compact
    return text


def validate_cell(value, rule: ColumnRule) -> Optional[tuple[str, str]]:
    if _is_blank(value):
        if rule.required:
            return (WARNING, "required — currently blank")
        return None

    text = str(value).strip()

    if rule.type == "enum":
        if text not in rule.options:
            return (ERROR, "must be one of the listed values")

    elif rule.type == "float" or rule.type == "number":
        try:
            num = float(text)
        except (TypeError, ValueError):
            return (ERROR, _range_message(rule))
        if (rule.min is not None and num < rule.min) or (
            rule.max is not None and num > rule.max
        ):
            return (ERROR, _range_message(rule))

    elif rule.type == "integer":
        try:
            num = float(text)
            if not num.is_integer():
                raise ValueError
        except (TypeError, ValueError):
            return (ERROR, _range_message(rule))
        if (rule.min is not None and num < rule.min) or (
            rule.max is not None and num > rule.max
        ):
            return (ERROR, _range_message(rule))

    elif rule.type == "date":
        if not _parse_date(text):
            return (ERROR, "not a valid date (YYYY-MM-DD)")

    if rule.max_length is not None and len(text) > rule.max_length:
        return (ERROR, f"too long (max {rule.max_length} characters)")

    if rule.regex is not None and re.fullmatch(rule.regex, text) is None:
        return (ERROR, rule.regex_hint or "does not match the required format")

    return None


def _fmt(n: float) -> str:
    text = str(int(n)) if float(n).is_integer() else str(n)
    return text.replace("-", "\u2212")


def _range_message(rule: ColumnRule) -> str:
    kind = "a whole number" if rule.type == "integer" else "a number"
    if rule.min is not None and rule.max is not None:
        return f"must be {kind}, {_fmt(rule.min)} to {_fmt(rule.max)}"
    if rule.min is not None:
        return f"must be {kind} \u2265 {_fmt(rule.min)}"
    if rule.max is not None:
        return f"must be {kind} \u2264 {_fmt(rule.max)}"
    return f"must be {kind}"


def _parse_date(text: str) -> Optional[datetime]:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def validate_edits(
    edits: dict[tuple, str], rules_by_column: dict[str, ColumnRule]
) -> dict[tuple, tuple[str, str]]:
    findings: dict[tuple, tuple[str, str]] = {}
    for (row_id, column), new_value in edits.items():
        rule = rules_by_column.get(column)
        if rule is None:
            continue
        finding = validate_cell(new_value, rule)
        if finding:
            findings[(row_id, column)] = finding
    return findings


def errors_only(findings: dict[tuple, tuple[str, str]]) -> dict[tuple, str]:
    return {k: msg for k, (sev, msg) in findings.items() if sev == ERROR}


def warnings_only(findings: dict[tuple, tuple[str, str]]) -> dict[tuple, str]:
    return {k: msg for k, (sev, msg) in findings.items() if sev == WARNING}
