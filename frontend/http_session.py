
"""
MODULE NAME
-----------
FRONTEND HTTP SESSION COOKIE UTILITIES

PURPOSE
-------
Issue, read, rotate, and expire browser identity cookies.

ENVIRONMENT / CONFIGURATION
---------------------------
FRONTEND_COOKIE_SECURE=true in HTTPS deployments.
FRONTEND_COOKIE_SECURE=false for local HTTP development only.

DEPENDENCIES
------------
Python standard library.
Starlette.
frontend.browser_session_binding.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
- Apply secure cookie attributes.
- Read registered browser identities.
- Issue replacement cookies.
- Expire browser cookies.

SECURITY NOTES
--------------
- Cookies are HttpOnly and SameSite=Strict.
- Secure cookies are mandatory in production HTTPS.
- Cookie values are opaque bearer secrets.
- HTTP request origin and CSRF validation are separate.
- This module does not authenticate Gradio event resources.
"""

from __future__ import annotations

from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import Response

from frontend.browser_session_binding import BrowserSessionBinding


COOKIE_NAME = "health_advisor_browser_session"
DEFAULT_COOKIE_MAX_AGE = 1800


@dataclass(frozen=True)
class HTTPSessionSettings:
    """Cookie policy for the frontend deployment."""

    secure: bool = True
    max_age: int = DEFAULT_COOKIE_MAX_AGE

    def __post_init__(self) -> None:
        if self.max_age <= 0:
            raise ValueError(
                "Cookie lifetime must be positive."
            )


class HTTPSessionCookies:
    """Manage opaque browser identity cookies."""

    def __init__(
        self,
        binding: BrowserSessionBinding,
        *,
        settings: HTTPSessionSettings | None = None,
    ) -> None:
        self._binding = binding
        self._settings = settings or HTTPSessionSettings()

    def read_identity(self, request: Request) -> str | None:
        """
        Return a registered browser identity.

        An unknown cookie is never accepted as a new identity.
        """

        identity = request.cookies.get(COOKIE_NAME)

        if not identity or not self._binding.exists(identity):
            return None

        return identity

    def set_identity(
        self,
        response: Response,
        identity: str,
    ) -> None:
        """Issue or replace a server-controlled browser cookie."""

        if not self._binding.exists(identity):
            raise ValueError(
                "Cannot issue a cookie for an unknown session."
            )

        response.set_cookie(
            key=COOKIE_NAME,
            value=identity,
            max_age=self._settings.max_age,
            path="/",
            secure=self._settings.secure,
            httponly=True,
            samesite="strict",
        )

    @staticmethod
    def clear_identity(response: Response) -> None:
        """Expire the browser identity cookie."""

        response.delete_cookie(
            key=COOKIE_NAME,
            path="/",
            httponly=True,
            samesite="strict",
        )