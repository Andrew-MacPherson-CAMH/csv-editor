from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class User:

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
    pass


class AuthProvider(ABC):

    name: str = "base"
    redirect_based: bool = False
    header_based: bool = False

    def __init__(self, settings: dict[str, Any]):
        self.settings = settings

    @abstractmethod
    def authenticate(self, username: str, password: str) -> Optional[User]:
        raise NotImplementedError

    def get_login_url(self, state: str) -> str:
        raise NotImplementedError

    def complete_login(self, code: str) -> Optional[User]:
        raise NotImplementedError

    def authenticate_from_headers(self, headers: Any) -> Optional[User]:
        raise NotImplementedError
