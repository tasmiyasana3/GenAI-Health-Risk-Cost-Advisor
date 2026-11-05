
"""
MODULE NAME
-----------
FRONTEND AUTHENTICATION ORIGIN GUARD

PURPOSE
-------
Validate the origin of browser requests that change
frontend authentication state.

ENVIRONMENT / CONFIGURATION
---------------------------
FRONTEND_ALLOWED_ORIGIN:
    The exact public origin of the frontend.

    Local example:
    http://127.0.0.1:7860

    Production example:
    https://app.example.com

DEPENDENCIES
------------
Python standard library.
Starlette.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
- Validate configured origins.
- Reject missing or malformed request origins.
- Reject cross-origin authentication requests.
- Require exact scheme, hostname, and effective port.
- Avoid trusting the incoming Host header as the origin policy.

SECURITY NOTES
--------------
- Use a trusted deployment configuration, not request.base_url.
- Do not allow wildcard origins.
- Never accept a missing Origin header on browser
  authentication-changing routes.
- This guard does not authenticate the user.
- This guard is not a substitute for session ownership,
  request-size limits, rate limiting, or CSRF token defenses.
- Reverse proxies must preserve the browser Origin header.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from starlette.requests import Request


class AuthenticationOriginError(ValueError):
    """An authentication request has an unacceptable origin."""


def normalize_origin(value: str) -> str:
    """
    Normalize one HTTP or HTTPS origin.

    Reject paths, credentials, queries, fragments,
    unsupported schemes, and malformed ports.
    """

    if not isinstance(value, str):
        raise ValueError("Origin must be a string.")

    value = value.strip()

    if not value:
        raise ValueError("Origin cannot be empty.")

    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Malformed origin.") from exc

    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or any(character.isspace() for character in value)
    ):
        raise ValueError("Invalid HTTP origin.")

    # Reject malformed authority strings, including
    # ambiguous separators and unbracketed IPv6 literals.
    if not parsed.netloc or "@" in parsed.netloc:
        raise ValueError("Invalid origin authority.")

    hostname = parsed.hostname.lower()

    if ":" in hostname:
        hostname = f"[{hostname}]"

    is_default_port = (
        (parsed.scheme == "http" and port == 80)
        or (parsed.scheme == "https" and port == 443)
    )

    suffix = (
        f":{port}"
        if port is not None and not is_default_port
        else ""
    )

    return f"{parsed.scheme}://{hostname}{suffix}"


class AuthenticationOriginGuard:
    """
    Check requests against one trusted frontend origin.

    A deployment can construct this once at startup and
    reuse it for every authentication-changing request.
    """

    def __init__(
        self,
        *,
        allowed_origin: str | None = None,
    ) -> None:
        if allowed_origin is None:
            allowed_origin = os.getenv(
                "FRONTEND_ALLOWED_ORIGIN",
                "",
            )

        if not allowed_origin.strip():
            raise ValueError(
                "FRONTEND_ALLOWED_ORIGIN must be configured."
            )

        self._allowed_origin = normalize_origin(
            allowed_origin
        )

    def validate(self, request: Request) -> None:
        """
        Reject a request unless its Origin matches exactly.

        The caller should translate
        AuthenticationOriginError into HTTP 403.
        """

        supplied_origin = request.headers.get("origin")

        if supplied_origin is None:
            raise AuthenticationOriginError(
                "Authentication request origin is required."
            )

        try:
            normalized = normalize_origin(
                supplied_origin
            )
        except ValueError as exc:
            raise AuthenticationOriginError(
                "Authentication request origin is invalid."
            ) from exc

        if normalized != self._allowed_origin:
            raise AuthenticationOriginError(
                "Authentication request origin is not allowed."
            )