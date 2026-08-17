"""OAuth redirect-callback decision logic — pure, no Streamlit imports.

Streamlit's AppTest has no way to simulate st.query_params, so the actual
"what does this redirect mean" decision is extracted here where it can be
unit-tested directly; app.py is just a thin shell around this that reads
st.query_params/st.session_state and calls the auth provider.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Optional


class OAuthCallbackKind(Enum):
    NONE = "none"                     # no relevant params -- show the login button
    DENIED = "denied"                 # google returned error= (user declined, etc.)
    CSRF_MISMATCH = "csrf_mismatch"   # state missing, or doesn't match what we issued
    EXCHANGE = "exchange"             # code + valid state -- ready to exchange


@dataclass(frozen=True)
class OAuthCallback:
    kind: OAuthCallbackKind
    code: Optional[str] = None
    error: Optional[str] = None


def interpret_callback(
    query_params: Mapping[str, str], expected_state: Optional[str]
) -> OAuthCallback:
    """`query_params`: a plain dict view of st.query_params (dict(st.query_params)).
    `expected_state`: the CSRF token this session issued (st.session_state's
    "oauth_state"), or None if this session never generated one (e.g. it
    expired/reset between rendering the login link and the redirect back).
    """
    error = query_params.get("error")
    if error:
        return OAuthCallback(OAuthCallbackKind.DENIED, error=error)

    code = query_params.get("code")
    if not code:
        return OAuthCallback(OAuthCallbackKind.NONE)

    state = query_params.get("state")
    if not expected_state or state != expected_state:
        return OAuthCallback(OAuthCallbackKind.CSRF_MISMATCH)

    return OAuthCallback(OAuthCallbackKind.EXCHANGE, code=code)
