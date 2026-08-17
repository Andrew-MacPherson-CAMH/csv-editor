"""Fake google.cloud.storage / google.cloud.bigquery / google.oauth2.id_token
/ google.auth.transport.requests modules, installed into sys.modules so the
lazy `from google.cloud import X` (etc.) imports inside providers/*.py
resolve to these fakes instead of requiring the real, optional packages to
be installed. Lets the whole GCP-touching logic path be exercised in a
plain unit test — no real network, credentials, or `google-*` packages.

Safe regardless of call order: the real providers only do these imports
inside methods, never at module top level, so installing the fakes any
time before a provider method actually runs is enough.

Usage (matches the try/finally style already used by
tests/test_validation.py::test_audit_write_local_csv — no conftest.py,
no pytest fixtures, to stay consistent with the rest of this suite):

    handles = install_gcp_fakes()
    try:
        ...exercise a provider...
        assert handles.bq_calls == [...]
    finally:
        uninstall_gcp_fakes()
"""
from __future__ import annotations

import sys
import types
from typing import Any, Optional


class FakeBlob:
    def __init__(self, store: dict, key: tuple):
        self._store = store
        self._key = key

    def download_as_bytes(self) -> bytes:
        if self._key not in self._store:
            raise FileNotFoundError(f"no such blob: {self._key}")
        return self._store[self._key]

    def upload_from_string(self, data, content_type: Optional[str] = None) -> None:
        self._store[self._key] = data if isinstance(data, (bytes, bytearray)) else str(data).encode()


class FakeBucket:
    def __init__(self, store: dict, bucket_name: str):
        self._store = store
        self._bucket_name = bucket_name

    def blob(self, path: str) -> FakeBlob:
        return FakeBlob(self._store, (self._bucket_name, path))


class FakeStorageClient:
    def __init__(self, handles: "FakeGcpHandles", *args, **kwargs):
        self._handles = handles

    def bucket(self, name: str) -> FakeBucket:
        return FakeBucket(self._handles.blob_store, name)


class FakeBigQueryClient:
    def __init__(self, handles: "FakeGcpHandles", *args, **kwargs):
        self._handles = handles

    def insert_rows_json(self, table: str, rows: list[dict]) -> list:
        self._handles.bq_calls.append((table, rows))
        return list(self._handles.bq_errors)


def _default_verify_oauth2_token(token, request, audience):
    raise RuntimeError(
        "id_token.verify_oauth2_token not stubbed for this test — set "
        "handles.id_token_module.verify_oauth2_token to a fake before calling."
    )


class FakeGcpHandles:
    """Returned by install_gcp_fakes(). Inspect/mutate these to control and
    assert on what a test's provider did:
      blob_store        {(bucket, path): bytes} -- backs GCS reads/writes
      bq_calls          [(table_ref, rows), ...] -- every insert_rows_json call
      bq_errors         list returned by insert_rows_json (empty = success;
                         set to a non-empty list to simulate a rejected insert)
      id_token_module   the fake google.oauth2.id_token module -- set
                         .verify_oauth2_token to a test-specific fake
    """

    def __init__(self):
        self.blob_store: dict = {}
        self.bq_calls: list = []
        self.bq_errors: list = []
        self.id_token_module: Optional[types.ModuleType] = None


_original_modules: dict[str, Any] = {}


def _install_module(
    name: str, module: types.ModuleType, parent: types.ModuleType, attr: str
) -> None:
    _original_modules.setdefault(name, sys.modules.get(name))
    sys.modules[name] = module
    setattr(parent, attr, module)


def install_gcp_fakes() -> FakeGcpHandles:
    handles = FakeGcpHandles()

    import google  # the real (namespace) package -- already installed

    cloud_mod = types.ModuleType("google.cloud")
    storage_mod = types.ModuleType("google.cloud.storage")
    storage_mod.Client = lambda *a, **kw: FakeStorageClient(handles, *a, **kw)
    bigquery_mod = types.ModuleType("google.cloud.bigquery")
    bigquery_mod.Client = lambda *a, **kw: FakeBigQueryClient(handles, *a, **kw)

    oauth2_mod = types.ModuleType("google.oauth2")
    id_token_mod = types.ModuleType("google.oauth2.id_token")
    id_token_mod.verify_oauth2_token = _default_verify_oauth2_token

    auth_mod = types.ModuleType("google.auth")
    transport_mod = types.ModuleType("google.auth.transport")
    transport_requests_mod = types.ModuleType("google.auth.transport.requests")
    transport_requests_mod.Request = lambda *a, **kw: object()

    _install_module("google.cloud", cloud_mod, google, "cloud")
    _install_module("google.cloud.storage", storage_mod, cloud_mod, "storage")
    _install_module("google.cloud.bigquery", bigquery_mod, cloud_mod, "bigquery")
    _install_module("google.oauth2", oauth2_mod, google, "oauth2")
    _install_module("google.oauth2.id_token", id_token_mod, oauth2_mod, "id_token")
    _install_module("google.auth", auth_mod, google, "auth")
    _install_module("google.auth.transport", transport_mod, auth_mod, "transport")
    _install_module("google.auth.transport.requests", transport_requests_mod, transport_mod, "requests")

    handles.id_token_module = id_token_mod
    return handles


def uninstall_gcp_fakes() -> None:
    for name, original in _original_modules.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original
    _original_modules.clear()
