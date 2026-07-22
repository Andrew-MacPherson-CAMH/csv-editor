"""End-to-end view tests via Streamlit's AppTest.

Run with:  CSV_EDITOR_TESTMODE=1 python -m pytest tests/ -q
(TESTMODE disables dataframe cell-selection, which AppTest can't serialize.)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("CSV_EDITOR_TESTMODE", "1")

from streamlit.testing.v1 import AppTest

from providers.auth.base import User

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def fresh(**session):
    # Run once to create session state, log the user in and let the data
    # load (which resets `edits`), then seed the remaining state.
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.session_state["user"] = session.pop("user", _user())
    at = at.run()
    for k, v in session.items():
        at.session_state[k] = v
    return at.run()


def test_login_success_and_failure():
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.text_input(key="login_email").set_value("admin")
    at.text_input(key="login_password").set_value("nope")
    at = at.button[0].set_value(True).run()
    assert at.session_state["user"] is None
    assert any("Incorrect" in e.value for e in at.error)

    at.text_input(key="login_email").set_value("admin")
    at.text_input(key="login_password").set_value("admin")
    at = at.button[0].set_value(True).run()
    assert at.session_state["user"] is not None


def _user():
    return User(username="admin", display_name="admin", provider="mock")


def test_review_validation_gates_publish():
    at = fresh(
        user=_user(),
        view="review",
        edits={(2, "email"): "broken-email", (2, "seats"): "42", (5, "city"): "Portland"},
    )
    assert not at.exception
    body = " ".join(md.value for md in at.markdown)
    assert "Review changes" in body and "invalid" in body
    publish = [b for b in at.button if "Publish" in (b.label or "")][0]
    assert publish.disabled

    at.session_state["edits"][(2, "email")] = "fixed@example.com"
    at = at.run()
    body = " ".join(md.value for md in at.markdown)
    assert "2 rows · 3 cells changed" in body
    publish = [b for b in at.button if "Publish" in (b.label or "")][0]
    assert not publish.disabled


def test_search_keeps_hidden_edits_and_badge():
    at = fresh(
        user=_user(),
        edits={(2, "email"): "a@b.co", (5, "city"): "Portland", (9, "seats"): "7"},
        search="portland",
    )
    assert not at.exception
    body = " ".join(md.value for md in at.markdown)
    labels = " ".join(b.label or "" for b in at.button)
    assert "matching" in body
    assert "Clear search" in labels
    assert "(3)" in labels  # badge count unchanged by filtering


def test_editing_view_renders():
    at = fresh(user=_user())
    assert not at.exception
    body = " ".join(md.value for md in at.markdown)
    assert "120 of 120 rows" in body.replace(",", "")
