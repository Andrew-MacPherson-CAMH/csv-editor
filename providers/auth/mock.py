from __future__ import annotations

from typing import Optional

from providers.auth.base import AuthProvider, User


class MockAuthProvider(AuthProvider):
    name = "mock"

    def authenticate(self, username: str, password: str) -> Optional[User]:
        users: dict[str, str] = self.settings.get("users", {}) or {}
        if users.get(username) == password and password != "":
            return User(username=username, display_name=username, provider=self.name)
        return None
