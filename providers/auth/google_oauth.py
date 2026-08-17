"""Google OAuth (redirect-based) auth provider.

The app itself performs the full OAuth authorization-code flow — this is
NOT the "trust a header from an external proxy" (IAP) pattern; the app
renders a login link, Google redirects the browser back with a `code`,
and the app exchanges that code for an ID token directly.

Config (auth.google_oauth):
    client_id_env:     GOOGLE_OAUTH_CLIENT_ID       # env var holding the client id
    client_secret_env: GOOGLE_OAUTH_CLIENT_SECRET   # env var holding the client secret
    client_id / client_secret: "..."                # inline fallback (avoid committing)
    redirect_uri:       https://<your-app>/           # must exactly match the OAuth
                                                        # client's authorized redirect URI

Requires: pip install google-auth
(google.oauth2.id_token + google.auth.transport.requests both ship in the
`google-auth` package — NOT google-auth-oauthlib or google-api-python-client.
The token exchange POST itself uses the project's existing `requests` dep.)
"""
from __future__ import annotations

import os
from typing import Any, Optional
from urllib.parse import urlencode

import requests

from providers.auth.base import AuthError, AuthProvider, User

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"


class GoogleOAuthProvider(AuthProvider):
    name = "google_oauth"
    redirect_based = True

    def __init__(self, settings: dict[str, Any]):
        super().__init__(settings)
        self._client_id = self._required("client_id")
        self._client_secret = self._required("client_secret")
        self._redirect_uri = settings.get("redirect_uri")
        if not self._redirect_uri:
            raise AuthError("auth.google_oauth.redirect_uri is not configured")

    def _required(self, key: str) -> str:
        env_name = self.settings.get(f"{key}_env")
        value = (os.environ.get(env_name) if env_name else None) or self.settings.get(key)
        if not value:
            raise AuthError(
                f"Google OAuth {key} not configured. Set the env var "
                f"{env_name or f'GOOGLE_OAUTH_{key.upper()}'} or "
                f"auth.google_oauth.{key} in config.yaml."
            )
        return value

    def authenticate(self, username: str, password: str) -> Optional[User]:
        raise AuthError(
            "google_oauth requires the redirect-based login flow, not username/password."
        )

    def get_login_url(self, state: str) -> str:
        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
        }
        return f"{AUTH_ENDPOINT}?{urlencode(params)}"

    def complete_login(self, code: str) -> Optional[User]:
        try:
            from google.auth.transport import requests as google_requests
            from google.oauth2 import id_token
        except ImportError as exc:
            raise AuthError(
                "google-auth is not installed. Run: pip install google-auth"
            ) from exc

        try:
            resp = requests.post(
                TOKEN_ENDPOINT,
                data={
                    "code": code,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "redirect_uri": self._redirect_uri,
                    "grant_type": "authorization_code",
                },
                timeout=15,
            )
        except requests.RequestException as exc:
            raise AuthError(f"Could not reach Google's token endpoint: {exc}") from exc

        if resp.status_code != 200:
            raise AuthError(
                f"Google token exchange failed ({resp.status_code}): {resp.text[:200]}"
            )

        token_data = resp.json()
        raw_id_token = token_data.get("id_token")
        if not raw_id_token:
            raise AuthError("Google's token response did not include an id_token.")

        try:
            claims = id_token.verify_oauth2_token(
                raw_id_token, google_requests.Request(), self._client_id
            )
        except Exception as exc:  # google-auth's exact exception type varies by version
            raise AuthError(f"Invalid Google ID token: {exc}") from exc

        if claims.get("email_verified") is False:
            return None  # rejected login, not an infra failure

        email = claims.get("email")
        if not email:
            raise AuthError("Google ID token did not include an email claim.")
        given = claims.get("given_name", "")
        family = claims.get("family_name", "")
        display_name = f"{given} {family}".strip() or email

        return User(username=email, display_name=display_name, provider=self.name)
