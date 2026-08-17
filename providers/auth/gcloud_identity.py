from __future__ import annotations

import os
from typing import Optional

import requests

from providers.auth.base import AuthError, AuthProvider, User

_SIGN_IN_URL = (
    "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
)

_BAD_CREDENTIAL_CODES = {
    "EMAIL_NOT_FOUND",
    "INVALID_PASSWORD",
    "INVALID_LOGIN_CREDENTIALS",
    "USER_DISABLED",
    "INVALID_EMAIL",
}


class GcloudIdentityAuthProvider(AuthProvider):
    name = "gcloud_identity"

    def _api_key(self) -> str:
        env_name = self.settings.get("api_key_env")
        key = (os.environ.get(env_name) if env_name else None) or self.settings.get(
            "api_key"
        )
        if not key:
            raise AuthError(
                "Google Identity Platform API key not configured. Set the "
                f"env var {env_name or 'GCP_IDENTITY_API_KEY'} or "
                "auth.gcloud_identity.api_key in config.yaml."
            )
        return key

    def authenticate(self, username: str, password: str) -> Optional[User]:
        try:
            resp = requests.post(
                _SIGN_IN_URL,
                params={"key": self._api_key()},
                json={
                    "email": username,
                    "password": password,
                    "returnSecureToken": True,
                },
                timeout=15,
            )
        except requests.RequestException as exc:
            raise AuthError(f"Could not reach Google Identity Platform: {exc}") from exc

        if resp.status_code == 200:
            body = resp.json()
            email = body.get("email", username)
            return User(
                username=email,
                display_name=body.get("displayName") or email,
                provider=self.name,
            )

        code = (
            resp.json().get("error", {}).get("message", "")
            if resp.headers.get("content-type", "").startswith("application/json")
            else ""
        )
        if any(code.startswith(c) for c in _BAD_CREDENTIAL_CODES):
            return None
        raise AuthError(f"Identity Platform error ({resp.status_code}): {code or resp.text[:200]}")
