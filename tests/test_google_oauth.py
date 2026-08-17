"""Unit tests for providers.auth.google_oauth.GoogleOAuthProvider.

Uses tests/stubs/gcp_fakes.py to stand in for google-auth (not installed
by default -- it's an optional dependency, see requirements.txt) and
unittest.mock to stand in for the token-exchange HTTP call (requests is
already a hard project dependency, so no new test dependency is needed).

Run with:  python -m pytest tests/ -q
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from providers.auth.base import AuthError
from tests.stubs.gcp_fakes import install_gcp_fakes, uninstall_gcp_fakes

SETTINGS = {
    "client_id": "test-client-id",
    "client_secret": "test-client-secret",
    "redirect_uri": "https://app.example.com/",
}


class _FakeResponse:
    def __init__(self, status_code=200, body=None, text=""):
        self.status_code = status_code
        self._body = body or {}
        self.text = text

    def json(self):
        return self._body


def _provider():
    from providers.auth.google_oauth import GoogleOAuthProvider
    return GoogleOAuthProvider(dict(SETTINGS))


def test_missing_client_id_raises_immediately():
    from providers.auth.google_oauth import GoogleOAuthProvider
    try:
        GoogleOAuthProvider({"client_secret": "x", "redirect_uri": "https://x/"})
        assert False, "expected AuthError"
    except AuthError:
        pass


def test_missing_redirect_uri_raises_immediately():
    from providers.auth.google_oauth import GoogleOAuthProvider
    try:
        GoogleOAuthProvider({"client_id": "x", "client_secret": "y"})
        assert False, "expected AuthError"
    except AuthError:
        pass


def test_get_login_url_contains_client_id_redirect_and_state():
    provider = _provider()
    url = provider.get_login_url("csrf-token-123")
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=test-client-id" in url
    assert "state=csrf-token-123" in url
    assert "scope=openid" in url


def test_authenticate_is_not_supported_for_this_provider():
    provider = _provider()
    try:
        provider.authenticate("a@b.com", "pw")
        assert False, "expected AuthError"
    except AuthError:
        pass


def test_complete_login_happy_path_returns_user():
    handles = install_gcp_fakes()
    try:
        provider = _provider()
        handles.id_token_module.verify_oauth2_token = lambda token, req, aud: {
            "email": "person@example.com",
            "given_name": "Ada",
            "family_name": "Lovelace",
            "email_verified": True,
        }
        with patch.object(
            requests, "post",
            return_value=_FakeResponse(200, {"id_token": "fake.jwt"}),
        ):
            user = provider.complete_login("authcode")
        assert user is not None
        assert user.username == "person@example.com"
        assert user.display_name == "Ada Lovelace"
        assert user.provider == "google_oauth"
    finally:
        uninstall_gcp_fakes()


def test_complete_login_falls_back_to_email_when_name_claims_missing():
    handles = install_gcp_fakes()
    try:
        provider = _provider()
        handles.id_token_module.verify_oauth2_token = lambda token, req, aud: {
            "email": "person@example.com",
            "email_verified": True,
        }
        with patch.object(
            requests, "post",
            return_value=_FakeResponse(200, {"id_token": "fake.jwt"}),
        ):
            user = provider.complete_login("authcode")
        assert user.display_name == "person@example.com"
    finally:
        uninstall_gcp_fakes()


def test_complete_login_rejects_unverified_email_as_bad_login_not_infra_error():
    handles = install_gcp_fakes()
    try:
        provider = _provider()
        handles.id_token_module.verify_oauth2_token = lambda token, req, aud: {
            "email": "person@example.com",
            "email_verified": False,
        }
        with patch.object(
            requests, "post",
            return_value=_FakeResponse(200, {"id_token": "fake.jwt"}),
        ):
            user = provider.complete_login("authcode")
        assert user is None
    finally:
        uninstall_gcp_fakes()


def test_complete_login_token_exchange_http_failure_raises_autherror():
    install_gcp_fakes()
    try:
        provider = _provider()
        with patch.object(
            requests, "post",
            return_value=_FakeResponse(400, text="invalid_grant"),
        ):
            try:
                provider.complete_login("bad-code")
                assert False, "expected AuthError"
            except AuthError:
                pass
    finally:
        uninstall_gcp_fakes()


def test_complete_login_missing_id_token_in_response_raises_autherror():
    install_gcp_fakes()
    try:
        provider = _provider()
        with patch.object(
            requests, "post",
            return_value=_FakeResponse(200, {"access_token": "no-id-token-here"}),
        ):
            try:
                provider.complete_login("authcode")
                assert False, "expected AuthError"
            except AuthError:
                pass
    finally:
        uninstall_gcp_fakes()


def test_complete_login_invalid_token_signature_raises_autherror():
    handles = install_gcp_fakes()
    try:
        provider = _provider()

        def _boom(token, req, aud):
            raise ValueError("bad signature")

        handles.id_token_module.verify_oauth2_token = _boom
        with patch.object(
            requests, "post",
            return_value=_FakeResponse(200, {"id_token": "fake.jwt"}),
        ):
            try:
                provider.complete_login("authcode")
                assert False, "expected AuthError"
            except AuthError:
                pass
    finally:
        uninstall_gcp_fakes()


def test_complete_login_without_google_auth_installed_raises_friendly_autherror():
    # No install_gcp_fakes() here -- exercises the real ImportError path
    # when google-auth genuinely isn't installed (it's optional).
    import sys as _sys
    saved = {
        name: _sys.modules.pop(name, None)
        for name in ("google.oauth2", "google.oauth2.id_token",
                      "google.auth", "google.auth.transport", "google.auth.transport.requests")
    }
    try:
        provider = _provider()
        try:
            provider.complete_login("authcode")
            assert False, "expected AuthError"
        except AuthError as exc:
            assert "google-auth" in str(exc)
    finally:
        for name, mod in saved.items():
            if mod is not None:
                _sys.modules[name] = mod
