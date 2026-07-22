"""Auth provider interface.

To add a provider:
  1. Subclass AuthProvider and implement authenticate().
  2. Register it in providers/auth/__init__.py.
  3. Point `auth.provider` at it in config.yaml.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class User:
    """Minimal authenticated identity, provider-agnostic."""

    username: str
    display_name: str
    provider: str

    @property
    def initials(self) -> str:
        parts = [p for p in self.display_name.replace("@", " ").split() if p]
        if not parts:
            return "?"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[-1][0]).upper()


class AuthError(Exception):
    """Raised for provider/config failures (not for bad credentials)."""


class AuthProvider(ABC):
    """Username/password authentication backend."""

    name: str = "base"

    def __init__(self, settings: dict[str, Any]):
        self.settings = settings

    @abstractmethod
    def authenticate(self, username: str, password: str) -> Optional[User]:
        """Return a User on success, None on bad credentials.

        Raise AuthError for infrastructure problems (bad config,
        network failure) so the UI can distinguish them from a wrong
        password.
        """
        raise NotImplementedError
