from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class PublishOutcome:
    ok: bool
    blocking_error: Optional[str] = None
    audit_warning: Optional[str] = None


def publish_with_audit(
    provider: Any,
    write_data: Callable[[], None],
    metadata: dict[str, Any],
    audit_records: list[dict[str, Any]],
) -> PublishOutcome:
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
