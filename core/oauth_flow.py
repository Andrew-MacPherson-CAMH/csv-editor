from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Optional


class OAuthCallbackKind(Enum):
    NONE = "none"
    DENIED = "denied"
    CSRF_MISMATCH = "csrf_mismatch"
    EXCHANGE = "exchange"


@dataclass(frozen=True)
class OAuthCallback:
    kind: OAuthCallbackKind
    code: Optional[str] = None
    error: Optional[str] = None


def interpret_callback(
    query_params: Mapping[str, str], expected_state: Optional[str]
) -> OAuthCallback:
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
