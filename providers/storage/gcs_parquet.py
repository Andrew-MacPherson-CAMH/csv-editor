from __future__ import annotations

import io
from typing import Any

import pandas as pd

from providers.storage.base import ROW_ID, EditMap, StorageError, StorageProvider


class GcsParquetStorageProvider(StorageProvider):
    name = "gcs_parquet"
    audit_before_data_write = True
    supports_import = True

    def __init__(self, settings: dict[str, Any]):
        super().__init__(settings)
        for key in ("bucket", "blob_path"):
            if not settings.get(key):
                raise StorageError(f"storage.gcs_parquet.{key} is required")
        change_log = settings.get("change_log") or {}
        for key in ("project", "dataset", "table"):
            if not change_log.get(key):
                raise StorageError(f"storage.gcs_parquet.change_log.{key} is required")

        try:
            from google.cloud import bigquery, storage  # noqa: F401
        except ImportError as exc:
            raise StorageError(
                "google-cloud-storage and google-cloud-bigquery are not installed. "
                "Run: pip install google-cloud-storage google-cloud-bigquery"
            ) from exc
        try:
            import pyarrow  # noqa: F401
        except ImportError as exc:
            raise StorageError(
                "pyarrow is not installed. Run: pip install pyarrow"
            ) from exc


    def _storage_client(self):
        from google.cloud import storage

        return storage.Client()

    def _bigquery_client(self):
        from google.cloud import bigquery

        change_log = self.settings["change_log"]
        return bigquery.Client(
            project=change_log["project"], location=change_log.get("location")
        )

    def _blob(self):
        return self._storage_client().bucket(self.settings["bucket"]).blob(
            self.settings["blob_path"]
        )

    @property
    def _change_log_ref(self) -> str:
        c = self.settings["change_log"]
        return f"{c['project']}.{c['dataset']}.{c['table']}"


    def load(self) -> pd.DataFrame:
        try:
            data = self._blob().download_as_bytes()
        except Exception as exc:
            raise StorageError(f"GCS read failed: {exc}") from exc

        buf = io.BytesIO(data)
        try:
            df = pd.read_parquet(buf, engine="pyarrow")
        except Exception as exc:
            raise StorageError(f"Could not parse parquet data: {exc}") from exc
        finally:
            buf.close()

        id_column = self.settings.get("id_column")
        if id_column:
            if df[id_column].duplicated().any():
                raise StorageError(f"id_column '{id_column}' has duplicate values")
            df = df.set_index(df[id_column].rename(ROW_ID), drop=False)
        else:
            df.index = pd.RangeIndex(len(df), name=ROW_ID)
        return df.astype(str)

    def _write_parquet(self, df: pd.DataFrame) -> None:
        buf = io.BytesIO()
        try:
            df.to_parquet(buf, engine="pyarrow", index=False)
            data = buf.getvalue()
        finally:
            buf.close()
        try:
            self._blob().upload_from_string(data, content_type="application/octet-stream")
        except Exception as exc:
            raise StorageError(f"GCS write failed: {exc}") from exc

    def apply_edits(self, df: pd.DataFrame, edits: EditMap) -> None:
        updated = df.copy()
        for (row_id, column), value in edits.items():
            updated.loc[row_id, column] = value
        self._write_parquet(updated)

    def replace_all(self, new_df: pd.DataFrame) -> None:
        self._write_parquet(new_df)

    def write_audit(self, metadata, records) -> None:
        if not records:
            return
        try:
            bq_errors = self._bigquery_client().insert_rows_json(
                self._change_log_ref, records
            )
        except Exception as exc:
            raise StorageError(f"Change log write to {self._change_log_ref} failed: {exc}") from exc
        if bq_errors:
            raise StorageError(
                f"Change log write to {self._change_log_ref} rejected rows: {bq_errors}"
            )

    def display_name(self) -> str:
        return self.settings["blob_path"].rsplit("/", 1)[-1]
