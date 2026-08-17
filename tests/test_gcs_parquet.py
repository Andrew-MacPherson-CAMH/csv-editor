"""Unit tests for providers.storage.gcs_parquet.GcsParquetStorageProvider.

Uses tests/stubs/gcp_fakes.py to stand in for google-cloud-storage and
google-cloud-bigquery (both optional dependencies, not installed by
default) so this exercises the real provider logic (parquet
serialization, edit patching, audit-write passthrough) without any real
GCP network access or credentials.

Run with:  python -m pytest tests/ -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from providers.storage.base import ROW_ID, StorageError
from tests.stubs.gcp_fakes import install_gcp_fakes, uninstall_gcp_fakes

SETTINGS = {
    "bucket": "test-bucket",
    "blob_path": "some/path/data.parquet",
    "change_log": {"project": "p", "dataset": "d", "table": "t"},
}


def _provider():
    from providers.storage.gcs_parquet import GcsParquetStorageProvider
    return GcsParquetStorageProvider(dict(SETTINGS))


def test_missing_required_settings_raise_immediately():
    from providers.storage.gcs_parquet import GcsParquetStorageProvider
    try:
        GcsParquetStorageProvider({"bucket": "b"})   # no blob_path, no change_log
        assert False, "expected StorageError"
    except StorageError:
        pass


def test_load_reflects_a_prior_replace_all_and_is_string_typed():
    install_gcp_fakes()
    try:
        provider = _provider()
        df = pd.DataFrame({"name": ["Alice", "Bob"], "seats": [1, 2]})
        provider.replace_all(df)

        loaded = provider.load()
        assert list(loaded["name"]) == ["Alice", "Bob"]
        assert list(loaded["seats"]) == ["1", "2"]   # normalized to strings
        assert loaded.index.name == ROW_ID
        assert list(loaded.index) == [0, 1]           # positional row ids
    finally:
        uninstall_gcp_fakes()


def test_replace_all_writes_exactly_one_object():
    handles = install_gcp_fakes()
    try:
        provider = _provider()
        provider.replace_all(pd.DataFrame({"name": ["A"]}))
        assert len(handles.blob_store) == 1
        key = ("test-bucket", "some/path/data.parquet")
        assert key in handles.blob_store
    finally:
        uninstall_gcp_fakes()


def test_apply_edits_patches_only_the_given_cells():
    install_gcp_fakes()
    try:
        provider = _provider()
        original = pd.DataFrame(
            {"name": ["Alice", "Bob"], "city": ["Ottawa", "Toronto"]},
            index=pd.Index([0, 1], name=ROW_ID),
        )
        provider.replace_all(original)
        provider.apply_edits(original, {(1, "city"): "Montreal"})

        loaded = provider.load()
        assert loaded.at[1, "city"] == "Montreal"
        assert loaded.at[0, "city"] == "Ottawa"   # untouched
    finally:
        uninstall_gcp_fakes()


def test_load_missing_blob_raises_storage_error():
    install_gcp_fakes()
    try:
        provider = _provider()   # nothing written yet -- blob doesn't exist
        try:
            provider.load()
            assert False, "expected StorageError"
        except StorageError:
            pass
    finally:
        uninstall_gcp_fakes()


def test_write_audit_passes_records_through_unchanged_and_ignores_metadata():
    handles = install_gcp_fakes()
    try:
        provider = _provider()
        records = [{"name": "Alice", "change_id": "CHG-1", "change_state": "after"}]
        provider.write_audit({"last_updated_at": "now", "last_updated_by": "x"}, records)
        assert len(handles.bq_calls) == 1
        table_ref, sent_rows = handles.bq_calls[0]
        assert table_ref == "p.d.t"
        assert sent_rows == records   # unchanged -- no metadata keys merged in
    finally:
        uninstall_gcp_fakes()


def test_write_audit_empty_records_is_a_noop():
    handles = install_gcp_fakes()
    try:
        provider = _provider()
        provider.write_audit({}, [])
        assert handles.bq_calls == []
    finally:
        uninstall_gcp_fakes()


def test_write_audit_rejected_rows_raise_storage_error():
    handles = install_gcp_fakes()
    try:
        provider = _provider()
        handles.bq_errors = [{"index": 0, "errors": [{"reason": "invalid"}]}]
        try:
            provider.write_audit({}, [{"name": "Alice"}])
            assert False, "expected StorageError"
        except StorageError:
            pass
    finally:
        uninstall_gcp_fakes()


def test_display_name_is_the_blob_filename():
    install_gcp_fakes()
    try:
        provider = _provider()
        assert provider.display_name() == "data.parquet"
    finally:
        uninstall_gcp_fakes()
