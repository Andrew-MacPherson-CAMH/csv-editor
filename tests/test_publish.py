"""Unit tests for core.publish's write-order branching.

Uses tiny duck-typed stub providers (not real or GCP-faked ones) -- this
module only cares about call order and error translation, not what any
real provider actually does.

Run with:  python -m pytest tests/ -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.publish import publish_with_audit


class StubProvider:
    def __init__(self, audit_before_data_write, fail_write_audit=False, fail_write_data=False):
        self.audit_before_data_write = audit_before_data_write
        self._fail_write_audit = fail_write_audit
        self._fail_write_data = fail_write_data
        self.calls: list[str] = []

    def write_audit(self, metadata, records):
        self.calls.append("audit")
        if self._fail_write_audit:
            raise RuntimeError("audit boom")


def _write_data(provider: StubProvider):
    def _write():
        provider.calls.append("data")
        if provider._fail_write_data:
            raise RuntimeError("data boom")
    return _write


def test_data_first_order_when_audit_before_data_write_is_false():
    provider = StubProvider(audit_before_data_write=False)
    outcome = publish_with_audit(provider, _write_data(provider), {}, [])
    assert outcome.ok
    assert provider.calls == ["data", "audit"]


def test_data_first_write_data_failure_blocks_and_skips_audit():
    provider = StubProvider(audit_before_data_write=False, fail_write_data=True)
    outcome = publish_with_audit(provider, _write_data(provider), {}, [])
    assert not outcome.ok
    assert outcome.blocking_error is not None
    assert provider.calls == ["data"]   # audit never attempted


def test_data_first_audit_failure_is_a_non_blocking_warning():
    provider = StubProvider(audit_before_data_write=False, fail_write_audit=True)
    outcome = publish_with_audit(provider, _write_data(provider), {}, [])
    assert outcome.ok   # data already succeeded
    assert outcome.audit_warning is not None
    assert provider.calls == ["data", "audit"]


def test_audit_first_order_when_audit_before_data_write_is_true():
    provider = StubProvider(audit_before_data_write=True)
    outcome = publish_with_audit(provider, _write_data(provider), {}, [])
    assert outcome.ok
    assert provider.calls == ["audit", "data"]


def test_audit_first_audit_failure_blocks_and_skips_data():
    provider = StubProvider(audit_before_data_write=True, fail_write_audit=True)
    outcome = publish_with_audit(provider, _write_data(provider), {}, [])
    assert not outcome.ok
    assert outcome.blocking_error is not None
    assert provider.calls == ["audit"]   # data never attempted


def test_audit_first_data_failure_after_audit_success_is_a_distinct_blocking_error():
    provider = StubProvider(audit_before_data_write=True, fail_write_data=True)
    outcome = publish_with_audit(provider, _write_data(provider), {}, [])
    assert not outcome.ok   # the audit trail is now ahead of reality -- must not be silent
    assert outcome.blocking_error is not None
    assert "manual reconciliation" in outcome.blocking_error
    assert provider.calls == ["audit", "data"]
