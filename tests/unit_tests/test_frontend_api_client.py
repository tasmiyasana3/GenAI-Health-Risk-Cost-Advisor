
"""
MODULE NAME
-----------
FRONTEND FASTAPI HTTP CLIENT UNIT TESTS

PURPOSE
-------
Verify the frontend HTTP transport and authentication
contracts without starting the backend or accessing
external services.

ENVIRONMENT / CONFIGURATION
---------------------------
Runs locally using pytest and httpx.MockTransport.

No database, API key, internet connection, or live
FastAPI server is required.

DEPENDENCIES
------------
pytest, httpx, frontend.api_client.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Safe API URL validation.
2. Registration response parsing.
3. Login credential extraction.
4. Refresh-cookie rotation.
5. Logout request behavior.
6. Origin header handling.
7. HTTP error handling.
8. Invalid backend responses.
9. Request-level cookie isolation.
10. Network timeout handling.

SECURITY NOTES
--------------
All credentials are synthetic.
Tests must not print or log authentication secrets.
No external model calls are permitted.
"""

import httpx
import pytest

from frontend.api_client import (
    FrontendAPIClient,
    FrontendAPIError,
    validate_api_base_url,
)


# =============================================================================
# TEST HELPERS
# =============================================================================

def make_client(handler):
    """Build a frontend API client with an offline transport."""

    return FrontendAPIClient(
        base_url="http://127.0.0.1:8000",
        transport=httpx.MockTransport(handler),
    )


def auth_response(
    access_token="test-access",
    refresh_token="test-refresh",
):
    """Create a synthetic successful authentication response."""

    return httpx.Response(
        200,
        json={
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": 900,
        },
        headers={
            "set-cookie": (
                f"refresh_token={refresh_token}; "
                "HttpOnly; Path=/auth; SameSite=Strict"
            ),
        },
    )


# =============================================================================
# CONFIGURATION TESTS
# =============================================================================

def test_local_api_url_is_accepted():
    """Loopback HTTP must be permitted for local development."""

    assert validate_api_base_url(
        "http://127.0.0.1:8000"
    ) == "http://127.0.0.1:8000"


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "ftp://127.0.0.1",
        "http://user:password@127.0.0.1:8000",
        "http://127.0.0.1:8000/private",
        "http://127.0.0.1:8000?token=secret",
    ],
)
def test_unsafe_api_urls_are_rejected(url):
    """Reject unsupported or unsafe backend URL configurations."""

    with pytest.raises(ValueError):
        validate_api_base_url(url)


# =============================================================================
# REGISTRATION TESTS
# =============================================================================

def test_registration_success():
    """Registration should parse the existing FastAPI contract."""

    def handler(request):
        assert request.url.path == "/auth/register"
        assert request.method == "POST"

        return httpx.Response(
            201,
            json={
                "user_id": "user-123",
                "email": "test@example.com",
                "created_at": "2026-11-04T12:00:00",
            },
        )

    client = make_client(handler)

    result = client.register(
        "test@example.com",
        "StrongPassword123!",
    )

    assert result.user_id == "user-123"
    assert result.email == "test@example.com"


def test_registration_conflict():
    """A duplicate account must produce a controlled error."""

    def handler(request):
        return httpx.Response(
            409,
            json={"detail": "Duplicate account."},
        )

    client = make_client(handler)

    with pytest.raises(FrontendAPIError) as error:
        client.register(
            "test@example.com",
            "StrongPassword123!",
        )

    assert error.value.status_code == 409


# =============================================================================
# LOGIN TESTS
# =============================================================================

def test_login_extracts_both_credentials():
    """Login must return access and refresh credentials."""

    def handler(request):
        assert request.url.path == "/auth/login"
        return auth_response()

    client = make_client(handler)

    result = client.login(
        "test@example.com",
        "StrongPassword123!",
    )

    assert result.access_token == "test-access"
    assert result.refresh_token == "test-refresh"
    assert result.expires_in == 900


def test_login_rejects_missing_refresh_cookie():
    """A login without a refresh cookie is incomplete."""

    def handler(request):
        return httpx.Response(
            200,
            json={
                "access_token": "test-access",
                "token_type": "bearer",
                "expires_in": 900,
            },
        )

    client = make_client(handler)

    with pytest.raises(FrontendAPIError):
        client.login(
            "test@example.com",
            "StrongPassword123!",
        )


def test_login_rejects_invalid_credentials():
    """HTTP 401 must become a safe authentication error."""

    def handler(request):
        return httpx.Response(
            401,
            json={"detail": "Invalid email or password."},
        )

    client = make_client(handler)

    with pytest.raises(FrontendAPIError) as error:
        client.login(
            "test@example.com",
            "incorrect-password",
        )

    assert error.value.status_code == 401


# =============================================================================
# REFRESH TESTS
# =============================================================================

def test_refresh_rotates_credentials():
    """Refresh must send the old cookie and return new credentials."""

    def handler(request):
        assert request.url.path == "/auth/refresh"
        assert request.headers["origin"] == (
            "http://127.0.0.1:8000"
        )
        assert (
            request.headers["cookie"]
            == "refresh_token=old-refresh"
        )

        return auth_response(
            access_token="new-access",
            refresh_token="new-refresh",
        )

    client = make_client(handler)

    result = client.refresh("old-refresh")

    assert result.access_token == "new-access"
    assert result.refresh_token == "new-refresh"


def test_refresh_rejects_missing_credentials():
    """Refresh cannot proceed without a refresh token."""

    client = make_client(
        lambda request: httpx.Response(200)
    )

    with pytest.raises(FrontendAPIError):
        client.refresh("")


# =============================================================================
# LOGOUT TESTS
# =============================================================================

def test_logout_sends_cookie_and_origin():
    """Logout must use the backend's cookie-authenticated route."""

    def handler(request):
        assert request.url.path == "/auth/logout"
        assert request.headers["origin"] == (
            "http://127.0.0.1:8000"
        )
        assert (
            request.headers["cookie"]
            == "refresh_token=test-refresh"
        )

        return httpx.Response(
            200,
            json={"message": "Logged out successfully."},
        )

    client = make_client(handler)

    assert client.logout("test-refresh") is None


# =============================================================================
# HTTP AND RESPONSE FAILURE TESTS
# =============================================================================

def test_invalid_json_is_rejected():
    """Malformed backend responses must not reach the UI."""

    def handler(request):
        return httpx.Response(
            200,
            text="not-json",
        )

    client = make_client(handler)

    with pytest.raises(FrontendAPIError):
        client.login(
            "test@example.com",
            "StrongPassword123!",
        )


def test_backend_timeout_is_handled():
    """A timeout must produce a controlled error."""

    def handler(request):
        raise httpx.ReadTimeout("Synthetic timeout.")

    client = make_client(handler)

    with pytest.raises(FrontendAPIError) as error:
        client.register(
            "test@example.com",
            "StrongPassword123!",
        )

    assert "timed out" in str(error.value)


def test_request_cookies_are_not_shared():
    """One operation must not retain another operation's cookie."""

    observed_cookies = []

    def handler(request):
        observed_cookies.append(
            request.headers.get("cookie")
        )

        if request.url.path == "/auth/login":
            return auth_response()

        return httpx.Response(
            201,
            json={
                "user_id": "user-456",
                "email": "other@example.com",
                "created_at": "2026-11-04T12:00:00",
            },
        )

    client = make_client(handler)

    client.login(
        "test@example.com",
        "StrongPassword123!",
    )

    client.register(
        "other@example.com",
        "StrongPassword456!",
    )

    assert observed_cookies == [None, None]