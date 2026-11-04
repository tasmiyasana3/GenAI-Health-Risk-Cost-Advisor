
"""
MODULE NAME
-----------
HTTP SESSION COOKIE TESTS

PURPOSE
-------
Verify secure cookie issuance, validation, and deletion.

ENVIRONMENT / CONFIGURATION
---------------------------
Offline pytest execution.

DEPENDENCIES
------------
pytest, Starlette.
frontend.browser_session_binding.
frontend.http_session.
frontend.session_binding.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
Cookie attributes, registered identities, and invalid cookies.

SECURITY NOTES
--------------
These tests do not replace real HTTP integration tests.
"""

import pytest

from starlette.requests import Request
from starlette.responses import Response

from frontend.browser_session_binding import BrowserSessionBinding
from frontend.http_session import (
    COOKIE_NAME,
    HTTPSessionCookies,
    HTTPSessionSettings,
)
from frontend.session_binding import SessionRegistry


def make_request(cookie: str | None = None) -> Request:
    headers = []

    if cookie is not None:
        headers.append(
            (
                b"cookie",
                f"{COOKIE_NAME}={cookie}".encode("ascii"),
            )
        )

    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "query_string": b"",
        }
    )


def test_secure_cookie_attributes():
    binding = BrowserSessionBinding(SessionRegistry())
    identity = binding.create()

    cookies = HTTPSessionCookies(binding)
    response = Response()

    cookies.set_identity(response, identity)

    header = response.headers["set-cookie"].lower()

    assert "httponly" in header
    assert "secure" in header
    assert "samesite=strict" in header
    assert "path=/" in header


def test_registered_identity_can_be_read():
    binding = BrowserSessionBinding(SessionRegistry())
    identity = binding.create()
    cookies = HTTPSessionCookies(binding)

    assert cookies.read_identity(make_request(identity)) == identity


def test_unknown_cookie_is_rejected():
    binding = BrowserSessionBinding(SessionRegistry())
    cookies = HTTPSessionCookies(binding)

    assert cookies.read_identity(make_request("forged")) is None


def test_missing_cookie_is_rejected():
    binding = BrowserSessionBinding(SessionRegistry())
    cookies = HTTPSessionCookies(binding)

    assert cookies.read_identity(make_request()) is None


def test_terminated_identity_is_rejected():
    binding = BrowserSessionBinding(SessionRegistry())
    identity = binding.create()

    binding.terminate(identity)

    cookies = HTTPSessionCookies(binding)

    assert cookies.read_identity(make_request(identity)) is None


def test_cookie_can_be_cleared():
    response = Response()

    HTTPSessionCookies.clear_identity(response)

    header = response.headers["set-cookie"].lower()

    assert COOKIE_NAME in header
    assert "max-age=0" in header


def test_invalid_cookie_lifetime_is_rejected():
    with pytest.raises(ValueError):
        HTTPSessionSettings(max_age=0)