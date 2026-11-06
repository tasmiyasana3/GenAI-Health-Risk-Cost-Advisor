
"""
MODULE NAME
-----------
PHASE 5.2.5B AUTHENTICATION HTTP SECURITY TESTS

PURPOSE
-------
Verify the interactive frontend authentication boundary
without using a real database or backend HTTP server.

ENVIRONMENT / CONFIGURATION
---------------------------
Offline pytest execution using FastAPI TestClient.

All backend authentication calls are replaced by a
deterministic fake client.

No Gemini, PostgreSQL, external API, or paid service
is required.

DEPENDENCIES
------------
pytest.
FastAPI TestClient.
unittest.mock.
frontend.server.
frontend.api_client.
frontend.http_session.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
- Authentication-page security headers.
- Fresh Content Security Policy nonces.
- Browser identity cookie attributes.
- Origin validation on authentication writes.
- Bounded request-body handling.
- Malformed and invalid authentication payloads.
- Registration and duplicate-account error mapping.
- Login success and failure responses.
- Server-side token non-disclosure.
- Logout cookie invalidation.
- Independent browser identities.
- Restricted Gradio routes.

SECURITY NOTES
--------------
The fake backend intentionally does not create real JWTs.
These tests verify the frontend HTTP boundary, not the
cryptographic correctness of backend token issuance.

Backend session revocation and token rotation remain
covered by their dedicated authentication tests.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock

import pytest

from fastapi.testclient import TestClient

from frontend.api_client import FrontendAPIError
from frontend.http_session import COOKIE_NAME
from frontend.server import (
    MAX_AUTH_REQUEST_BYTES,
    create_app,
)


TRUSTED_ORIGIN = "http://127.0.0.1:7860"
UNTRUSTED_ORIGIN = "https://untrusted.example"

REGISTER_PATH = "/frontend-auth/register"
LOGIN_PATH = "/frontend-auth/login"
LOGOUT_PATH = "/frontend-auth/logout"
STATUS_PATH = "/frontend-auth/status"

EMAIL = "security-test@example.com"
PASSWORD = "SafeLocalPassword123!"


@pytest.fixture
def fake_backend():
    """
    Provide an isolated backend substitute.

    No real HTTP connection can be made through this mock.
    """

    backend = MagicMock()

    backend.register.return_value = None

    return backend


@pytest.fixture
def application(fake_backend):
    """Build the real frontend with a mocked backend."""

    return create_app(
        secure_cookie=False,
        api_client=fake_backend,
        allowed_origin=TRUSTED_ORIGIN,
    )


@pytest.fixture
def client(application):
    """Create an independent browser-like HTTP client."""

    with TestClient(
        application,
        follow_redirects=False,
    ) as instance:
        yield instance


def bootstrap(client: TestClient) -> str:
    """Obtain a server-issued anonymous browser identity."""

    response = client.get("/")

    assert response.status_code == 303
    assert response.headers["location"] == "/auth"

    identity = client.cookies.get(COOKIE_NAME)

    assert identity

    return identity


def post_json(
    client: TestClient,
    path: str,
    payload: dict,
    origin: str | None = TRUSTED_ORIGIN,
):
    """Submit an authentication request with an explicit Origin."""

    headers = {}

    if origin is not None:
        headers["Origin"] = origin

    return client.post(
        path,
        json=payload,
        headers=headers,
    )


def registration_payload() -> dict:
    """Return valid fictional registration details."""

    return {
        "email": EMAIL,
        "password": PASSWORD,
    }


def login_payload() -> dict:
    """Return valid fictional login details."""

    return {
        "email": EMAIL,
        "password": PASSWORD,
    }


def test_authentication_page_security_headers(client):
    """Authentication HTML must not be cached or framed."""

    response = client.get("/auth")

    assert response.status_code == 200

    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-frame-options"] == "DENY"

    policy = response.headers["content-security-policy"]

    assert "default-src 'none'" in policy
    assert "frame-ancestors 'none'" in policy
    assert "connect-src 'self'" in policy
    assert "script-src 'nonce-" in policy


def test_authentication_page_uses_fresh_csp_nonce(client):
    """Two page renders must not reuse a script nonce."""

    first = client.get("/auth")
    second = client.get("/auth")

    pattern = r"script-src 'nonce-([^']+)'"

    first_match = re.search(
        pattern,
        first.headers["content-security-policy"],
    )

    second_match = re.search(
        pattern,
        second.headers["content-security-policy"],
    )

    assert first_match is not None
    assert second_match is not None

    assert first_match.group(1) != second_match.group(1)


def test_browser_cookie_security_attributes(client):
    """The browser identity cookie must be HttpOnly and strict."""

    response = client.get("/")

    cookie = response.headers["set-cookie"].lower()

    assert COOKIE_NAME.lower() in cookie
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "path=/" in cookie


def test_registration_succeeds_without_authenticating(client, fake_backend):
    """Account creation must not automatically sign in the user."""

    bootstrap(client)

    response = post_json(
        client,
        REGISTER_PATH,
        registration_payload(),
    )

    assert response.status_code == 201
    assert response.json() == {
        "registered": True,
        "authenticated": False,
    }

    fake_backend.register.assert_called_once_with(
        email=EMAIL,
        password=PASSWORD,
    )

    status = client.get(STATUS_PATH)

    assert status.status_code == 200
    assert status.json()["authenticated"] is False


def test_registration_requires_existing_browser_identity(
    client,
    fake_backend,
):
    """Registration without bootstrap must be rejected."""

    response = post_json(
        client,
        REGISTER_PATH,
        registration_payload(),
    )

    assert response.status_code == 401
    fake_backend.register.assert_not_called()


@pytest.mark.parametrize(
    "path,payload",
    [
        (REGISTER_PATH, registration_payload()),
        (LOGIN_PATH, login_payload()),
        (LOGOUT_PATH, {}),
    ],
)
@pytest.mark.parametrize(
    "origin",
    [
        None,
        UNTRUSTED_ORIGIN,
    ],
)
def test_authentication_writes_reject_untrusted_origins(
    client,
    fake_backend,
    path,
    payload,
    origin,
):
    """
    Missing or untrusted Origin must never reach
    the backend authentication operation.
    """

    bootstrap(client)

    response = post_json(
        client,
        path,
        payload,
        origin=origin,
    )

    assert response.status_code == 403

    fake_backend.register.assert_not_called()
    fake_backend.login.assert_not_called()
    fake_backend.logout.assert_not_called()


@pytest.mark.parametrize(
    "path",
    [
        REGISTER_PATH,
        LOGIN_PATH,
        LOGOUT_PATH,
    ],
)
def test_authentication_request_body_limit(
    client,
    fake_backend,
    path,
):
    """
    Oversized requests must be rejected before
    application handlers or backend services execute.
    """

    bootstrap(client)

    oversized_body = b"x" * (
        MAX_AUTH_REQUEST_BYTES + 1
    )

    response = client.post(
        path,
        content=oversized_body,
        headers={
            "Origin": TRUSTED_ORIGIN,
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 413
    assert response.headers["cache-control"] == "no-store"

    fake_backend.register.assert_not_called()
    fake_backend.login.assert_not_called()
    fake_backend.logout.assert_not_called()


def test_request_body_limit_accepts_small_valid_payload(
    client,
    fake_backend,
):
    """Accepted bodies must reach Pydantic without corruption."""

    bootstrap(client)

    response = post_json(
        client,
        REGISTER_PATH,
        registration_payload(),
    )

    assert response.status_code == 201
    fake_backend.register.assert_called_once()


def test_malformed_json_is_rejected_without_backend_call(
    client,
    fake_backend,
):
    """Malformed authentication JSON must not reach the backend."""

    bootstrap(client)

    response = client.post(
        REGISTER_PATH,
        content=b'{"email":',
        headers={
            "Origin": TRUSTED_ORIGIN,
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 422
    fake_backend.register.assert_not_called()


def test_short_registration_password_is_rejected(
    client,
    fake_backend,
):
    """Frontend field validation must reject short passwords."""

    bootstrap(client)

    response = post_json(
        client,
        REGISTER_PATH,
        {
            "email": EMAIL,
            "password": "short",
        },
    )

    assert response.status_code == 422
    fake_backend.register.assert_not_called()


def test_duplicate_registration_returns_safe_error(
    client,
    fake_backend,
):
    """Backend conflict details must not leak into the UI."""

    bootstrap(client)

    fake_backend.register.side_effect = FrontendAPIError(
        "Backend duplicate-account detail",
        status_code=409,
    )

    response = post_json(
        client,
        REGISTER_PATH,
        registration_payload(),
    )

    assert response.status_code == 409

    assert (
        response.json()["detail"]
        == "Account could not be created with these details."
    )

    assert "Backend duplicate-account detail" not in response.text


def test_registration_backend_failure_returns_503(
    client,
    fake_backend,
):
    """Unexpected backend registration status must fail safely."""

    bootstrap(client)

    fake_backend.register.side_effect = FrontendAPIError(
        "Internal backend detail",
        status_code=500,
    )

    response = post_json(
        client,
        REGISTER_PATH,
        registration_payload(),
    )

    assert response.status_code == 503
    assert "Internal backend detail" not in response.text


def test_invalid_login_credentials_return_401(
    client,
    application,
):
    """A backend authentication rejection must remain HTTP 401."""

    bootstrap(client)

    coordinator = application.state.auth_coordinator

    coordinator.login = MagicMock(
        side_effect=FrontendAPIError(
            "Sensitive backend login detail",
            status_code=401,
        )
    )

    response = post_json(
        client,
        LOGIN_PATH,
        login_payload(),
    )

    assert response.status_code == 401

    assert (
        response.json()["detail"]
        == "Authentication could not be completed."
    )

    assert "Sensitive backend login detail" not in response.text


def test_login_success_rotates_browser_cookie_without_tokens(
    client,
    application,
):
    """
    Successful login must rotate the browser identity.

    JWT and refresh credentials must not be returned
    in the browser-facing JSON response.
    """

    old_identity = bootstrap(client)

    coordinator = application.state.auth_coordinator

    # Use the real browser binding to create a replacement
    # identity while keeping backend login fully mocked.
    binding = application.state.browser_binding

    replacement = binding.create()

    coordinator.login = MagicMock(
        return_value=replacement
    )

    response = post_json(
        client,
        LOGIN_PATH,
        login_payload(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "authenticated": True
    }

    new_identity = client.cookies.get(COOKIE_NAME)

    assert new_identity
    assert new_identity != old_identity
    assert new_identity == replacement

    assert "access_token" not in response.text
    assert "refresh_token" not in response.text
    assert "jwt" not in response.text.lower()

    coordinator.login.assert_called_once_with(
        browser_identity=old_identity,
        email=EMAIL,
        password=PASSWORD,
    )


def test_logout_clears_browser_cookie(
    client,
    application,
):
    """Successful logout must clear browser identity."""

    bootstrap(client)

    coordinator = application.state.auth_coordinator

    coordinator.logout = MagicMock(
        return_value=None
    )

    response = post_json(
        client,
        LOGOUT_PATH,
        {},
    )

    assert response.status_code == 200
    assert response.json() == {
        "authenticated": False
    }

    assert client.cookies.get(COOKIE_NAME) is None

    assert client.get(STATUS_PATH).json() == {
        "authenticated": False
    }


def test_logout_backend_failure_is_not_reported_as_success(
    client,
    application,
):
    """Failed backend revocation must not produce HTTP 200."""

    bootstrap(client)

    coordinator = application.state.auth_coordinator

    coordinator.logout = MagicMock(
        side_effect=FrontendAPIError(
            "Revocation unavailable",
            status_code=503,
        )
    )

    response = post_json(
        client,
        LOGOUT_PATH,
        {},
    )

    assert response.status_code == 503
    assert client.cookies.get(COOKIE_NAME) is None


def test_independent_browser_clients_have_distinct_identities(
    application,
):
    """Two independent clients must never share browser cookies."""

    with (
        TestClient(
            application,
            follow_redirects=False,
        ) as browser_a,
        TestClient(
            application,
            follow_redirects=False,
        ) as browser_b,
    ):
        identity_a = bootstrap(browser_a)
        identity_b = bootstrap(browser_b)

        assert identity_a != identity_b

        assert browser_a.get(STATUS_PATH).json() == {
            "authenticated": False
        }

        assert browser_b.get(STATUS_PATH).json() == {
            "authenticated": False
        }


@pytest.mark.parametrize(
    "path,method",
    [
        ("/ui/gradio_api/queue/join", "POST"),
        ("/ui/gradio_api/upload", "POST"),
        ("/ui/gradio_api/call/predict", "POST"),
        ("/ui/gradio_api/file=private.pdf", "GET"),
    ],
)
def test_protected_gradio_operations_remain_disabled(
    client,
    path,
    method,
):
    """Browser identity must not enable private Gradio APIs."""

    bootstrap(client)

    response = client.request(method, path)

    assert response.status_code == 403