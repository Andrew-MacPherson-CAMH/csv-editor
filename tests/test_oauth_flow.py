"""Unit tests for core.oauth_flow's redirect-callback decision logic.

Run with:  python -m pytest tests/ -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.oauth_flow import OAuthCallbackKind, interpret_callback


def test_no_params_means_show_the_login_button():
    result = interpret_callback({}, expected_state=None)
    assert result.kind == OAuthCallbackKind.NONE


def test_error_param_means_denied():
    result = interpret_callback({"error": "access_denied"}, expected_state="abc")
    assert result.kind == OAuthCallbackKind.DENIED
    assert result.error == "access_denied"


def test_error_takes_priority_even_if_code_also_present():
    result = interpret_callback({"error": "access_denied", "code": "x"}, expected_state="abc")
    assert result.kind == OAuthCallbackKind.DENIED


def test_matching_state_means_ready_to_exchange():
    result = interpret_callback({"code": "authcode", "state": "abc"}, expected_state="abc")
    assert result.kind == OAuthCallbackKind.EXCHANGE
    assert result.code == "authcode"


def test_mismatched_state_is_csrf_rejected():
    result = interpret_callback({"code": "authcode", "state": "wrong"}, expected_state="abc")
    assert result.kind == OAuthCallbackKind.CSRF_MISMATCH


def test_missing_state_param_is_csrf_rejected():
    result = interpret_callback({"code": "authcode"}, expected_state="abc")
    assert result.kind == OAuthCallbackKind.CSRF_MISMATCH


def test_no_expected_state_is_csrf_rejected_even_if_a_state_param_is_present():
    # Session expired/reset between rendering the login link and the
    # redirect back -- there's nothing valid to compare against.
    result = interpret_callback({"code": "authcode", "state": "abc"}, expected_state=None)
    assert result.kind == OAuthCallbackKind.CSRF_MISMATCH
