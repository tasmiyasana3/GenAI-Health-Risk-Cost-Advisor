
"""
MODULE NAME
-----------
PHASE 5.2.4 AUTHENTICATION ORIGIN TESTS

PURPOSE
-------
Verify that browser authentication requests accept only
the explicitly trusted frontend origin.

ENVIRONMENT / CONFIGURATION
---------------------------
Offline pytest execution.
No network, database, Gemini, or paid services.

DEPENDENCIES
------------
pytest.
Starlette.
frontend.auth_origin.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
- Exact origin acceptance.
- Default-port normalization.
- Rejection of missing and malformed origins.
- Rejection of foreign domains and ports.
- Rejection of HTTPS-to-HTTP downgrade.
- Rejection of unsafe configuration.
- Configuration-independent behavior.

SECURITY NOTES
--------------
These are origin-policy unit tests, not end-to-end
CSRF or browser authentication tests.
"""

from __future__ import annotations

import pytest

from starlette.requests import Request

from frontend.auth_origin import (
    AuthenticationOriginError,
    AuthenticationOriginGuard,
    normalize_origin,
)


def make_request(origin: str | None) -> Request:
    """Create a minimal request with an optional Origin."""

    headers = []

    if origin is not None:
        headers.append(
            (
                b"origin",
                origin.encode("utf-8"),
            )
        )

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/auth/login",
            "headers": headers,
            "query_string": b"",
        }
    )


def test_exact_origin_is_allowed():
    guard = AuthenticationOriginGuard(
        allowed_origin="http://127.0.0.1:7860"
    )

    guard.validate(
        make_request("http://127.0.0.1:7860")
    )


def test_default_port_is_normalized():
    assert normalize_origin(
        "https://example.com:443"
    ) == "https://example.com"

    guard = AuthenticationOriginGuard(
        allowed_origin="https://example.com"
    )

    guard.validate(
        make_request("https://example.com:443")
    )


@pytest.mark.parametrize(
    "origin",
    [
        None,
        "",
        "null",
        "https://attacker.example",
        "http://127.0.0.1:7861",
        "https://127.0.0.1:7860",
        "http://localhost:7860",
        "http://127.0.0.1:7860.evil.example",
        "http://127.0.0.1:7860/path",
        "http://127.0.0.1:7860?redirect=1",
        "http://user:password@127.0.0.1:7860",
        "javascript:alert(1)",
    ],
)
def test_untrusted_origins_are_rejected(origin):
    guard = AuthenticationOriginGuard(
        allowed_origin="http://127.0.0.1:7860"
    )

    with pytest.raises(AuthenticationOriginError):
        guard.validate(make_request(origin))


@pytest.mark.parametrize(
    "origin",
    [
        "",
        "not-an-origin",
        "https://example.com/path",
        "https://example.com?x=1",
        "https://example.com#fragment",
        "ftp://example.com",
        "https://user@example.com",
        "https://example.com:invalid",
    ],
)
def test_invalid_configuration_is_rejected(origin):
    with pytest.raises(ValueError):
        AuthenticationOriginGuard(
            allowed_origin=origin
        )


def test_missing_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv(
        "FRONTEND_ALLOWED_ORIGIN",
        raising=False,
    )

    with pytest.raises(ValueError):
        AuthenticationOriginGuard()


def test_configured_origin_is_used(monkeypatch):
    monkeypatch.setenv(
        "FRONTEND_ALLOWED_ORIGIN",
        "http://127.0.0.1:7860",
    )

    guard = AuthenticationOriginGuard()

    guard.validate(
        make_request("http://127.0.0.1:7860")
    )