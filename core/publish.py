"""Shared publish helper — pure decision logic for write ORDER, not content.

Providers set `audit_before_data_write` (see providers/storage/base.py) to
pick which order they need; this is the one place that branch lives, so the
existing editor-publish flow and the new CSV-import-publish flow behave
identically for a given provider, and it can be unit-tested with tiny
duck-typed stub providers instead of real ones.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class PublishOutcome:
    ok: bool
    blocking_error: Optional[str] = None    # publish did not go through
    audit_warning: Optional[str] = None      # publish went through, audit did not


def publish_with_audit(
    provider: Any,
    write_data: Callable[[], None],
    metadata: dict[str, Any],
    audit_records: list[dict[str, Any]],
) -> PublishOutcome:
    """Run the data write and the audit write in the order `provider`
    requires, translating failures into a PublishOutcome the UI can show.

    audit_before_data_write = False (default; local_csv/bigquery today):
        write_data() first — failure blocks the publish outright, nothing
        else happens. write_audit() second — failure is a non-blocking
        warning, since the data write already succeeded.

    audit_before_data_write = True (gcs_parquet):
        write_audit() first — failure blocks the publish, nothing is
        written at all. write_data() second — if THIS fails, the audit
        trail is now ahead of reality (a change was logged that never
        actually landed). That's the safer failure mode for a compliance
        log than the reverse, but it must never be silent: surfaced as its
        own distinct blocking error rather than swallowed.
    """
    if provider.audit_before_data_write:
        try:
            provider.write_audit(metadata, audit_records)
        except Exception as exc:
            return PublishOutcome(
                ok=False, blocking_error=f"Publish failed — no changes were saved: {exc}"
            )
        try:
            write_data()
        except Exception as exc:
            return PublishOutcome(
                ok=False,
                blocking_error=(
                    "The change log was recorded, but the data write failed. This may "
                    f"need manual reconciliation: {exc}"
                ),
            )
        return PublishOutcome(ok=True)

    try:
        write_data()
    except Exception as exc:
        return PublishOutcome(
            ok=False, blocking_error=f"Publish failed — no changes were saved: {exc}"
        )
    try:
        provider.write_audit(metadata, audit_records)
    except Exception as exc:
        return PublishOutcome(
            ok=True,
            audit_warning=f"Changes were published, but the audit/metadata write failed: {exc}",
        )
    return PublishOutcome(ok=True)
