"""Import-flow tests, split two ways:

  * AppTest-driven UI checks against the real `local_csv`/`mock` providers
    (the app's zero-setup defaults) -- column-mismatch rejection, whole-file
    validation gating Publish, the unpublished-edits confirm dialog, and
    the discard path. None of these click the real "Yes, publish" button,
    so they never write to sample_data/resources.csv.
  * A direct (non-AppTest) provider-level test of LocalCsvStorageProvider's
    new replace_all()/supports_import against a tmpdir-copied CSV -- this
    is what actually exercises a full import-publish write, kept isolated
    from the real sample data the same way
    test_validation.py::test_audit_write_local_csv already does.

Run with:  python -m pytest tests/ -q
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from streamlit.testing.v1 import AppTest

from providers.auth.base import User
from providers.storage import create_storage_provider

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app.py")
DUMMY_CSV = os.path.join(ROOT, "sample_data", "dummy_988_data.csv")


def _user():
    return User(username="admin", display_name="admin", provider="mock")


def _fresh_logged_in():
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.session_state["user"] = _user()
    return at.run()


def _dummy_csv_bytes() -> bytes:
    with open(DUMMY_CSV, "rb") as fh:
        return fh.read()


def test_import_button_navigates_to_upload_page():
    at = _fresh_logged_in()
    import_btn = [b for b in at.button if b.label == "Import Data"][0]
    assert not import_btn.disabled   # local_csv supports_import = True
    at = import_btn.click().run()
    assert not at.exception
    body = " ".join(m.value for m in at.markdown)
    assert "Import data" in body
    assert at.session_state["view"] == "import_upload"


def test_missing_and_extra_columns_are_rejected_with_plain_language():
    at = _fresh_logged_in()
    at.session_state["view"] = "import_upload"
    at = at.run()

    bad_csv = b"name,phone_1,made_up_column\nAlice,123,x\n"
    at.file_uploader[0].set_value(("bad.csv", bad_csv, "text/csv"))
    at = at.run()
    validate_btn = [b for b in at.button if "Validate" in (b.label or "")][0]
    at = validate_btn.click().run()

    assert not at.exception
    errors = " ".join(e.value for e in at.error)
    assert "Missing required column" in errors
    assert "Unexpected column" in errors
    assert "made_up_column" in errors
    assert at.session_state["view"] == "import_upload"   # stayed put, didn't advance
    assert at.session_state["import_df"] is None


def test_valid_columns_advance_to_import_review_with_validation_findings():
    at = _fresh_logged_in()
    at.session_state["view"] = "import_upload"
    at = at.run()

    at.file_uploader[0].set_value(("dummy_988_data.csv", _dummy_csv_bytes(), "text/csv"))
    at = at.run()
    validate_btn = [b for b in at.button if "Validate" in (b.label or "")][0]
    at = validate_btn.click().run()

    assert not at.exception
    assert at.session_state["view"] == "import_review"
    assert len(at.session_state["import_df"]) == 17   # every row from the dummy file

    body = " ".join(m.value for m in at.markdown)
    assert "Review import" in body
    assert "invalid" in body   # dummy file has 2 deliberately-invalid cells
    publish_btn = [b for b in at.button if "Publish" in (b.label or "")][0]
    assert publish_btn.disabled   # errors present -> can't publish yet


def test_discard_import_clears_state_and_returns_to_editing():
    at = _fresh_logged_in()
    at.session_state["view"] = "import_upload"
    at = at.run()
    at.file_uploader[0].set_value(("dummy_988_data.csv", _dummy_csv_bytes(), "text/csv"))
    at = at.run()
    at = [b for b in at.button if "Validate" in (b.label or "")][0].click().run()
    assert at.session_state["view"] == "import_review"

    at = [b for b in at.button if b.label == "Discard import"][0].click().run()
    assert not at.exception
    assert at.session_state["view"] == "editing"
    assert at.session_state["import_df"] is None
    assert at.session_state["import_edits"] == {}


def test_importing_with_unpublished_edits_prompts_a_confirm_dialog():
    # Only checks that the dialog appears, not clicking through its buttons:
    # AppTest doesn't reliably re-invoke an @st.dialog function's body on
    # the rerun after a click inside it (confirmed against the pre-existing,
    # unmodified publish_dialog -- same st.session_state KeyError happens
    # clicking "Yes, publish" there too), which is exactly why the existing
    # test suite never clicks through publish_dialog either. This is an
    # AppTest/st.dialog limitation, not something to route around in the
    # app itself.
    at = _fresh_logged_in()
    at.session_state["edits"] = {(2, "website"): "https://x.example.ca"}
    at = at.run()

    import_btn = [b for b in at.button if b.label == "Import Data"][0]
    at = import_btn.click().run()
    assert not at.exception
    # Still on the editing view -- navigation waits for the dialog's choice.
    assert at.session_state["view"] == "editing"
    body = " ".join(m.value for m in at.markdown)
    assert "unpublished edit" in body.lower()
    labels = [b.label for b in at.button]
    assert "Discard and import" in labels
    assert "Cancel" in labels


def test_local_csv_replace_all_writes_a_full_new_dataset():
    """Direct provider-level test (no AppTest) -- exercises the actual
    full-replace write path against an isolated tmpdir copy, never
    touching the real sample_data files."""
    import pandas as pd

    from providers.storage.base import ROW_ID

    tmp_dir = tempfile.mkdtemp()
    try:
        csv_path = os.path.join(tmp_dir, "data.csv")
        shutil.copy(os.path.join(ROOT, "sample_data", "resources.csv"), csv_path)

        store = create_storage_provider("local_csv", {"path": csv_path, "id_column": None})
        assert store.supports_import

        original = store.load()
        assert len(original) == 96   # sanity: the real fixture's row count

        new_df = pd.DataFrame(
            {"name": ["Only Row"], "phone_1": ["555-0000"]},
            index=pd.RangeIndex(1, name=ROW_ID),
        )
        store.replace_all(new_df)

        reloaded = store.load()
        assert len(reloaded) == 1
        assert reloaded.iloc[0]["name"] == "Only Row"
    finally:
        shutil.rmtree(tmp_dir)
