
"""
MODULE NAME
-----------
PHASE 4.3D REFRESH API UNIT TESTS

PURPOSE
-------
Verify the FastAPI refresh endpoint without PostgreSQL.

ENVIRONMENT / CONFIGURATION
---------------------------
Uses FastAPI TestClient and pytest monkeypatch.

DEPENDENCIES
------------
FastAPI, pytest, api.auth_routes,
services.refresh_session_service.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
Successful refresh, cookie security, missing credentials,
cross-origin rejection, and infrastructure failures.

SECURITY NOTES
--------------
All credentials are synthetic.
Refresh secrets must never appear in JSON responses.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import auth_routes
from services.refresh_session_service import RefreshResult


# =============================================================================
# TEST CLIENT
# =============================================================================

def make_client() -> TestClient:
    """Create a minimal FastAPI application with auth routes."""
    application = FastAPI()
    application.include_router(auth_routes.router)

    return TestClient(application)


# =============================================================================
# SUCCESSFUL REFRESH
# =============================================================================

def test_successful_refresh_sets_secure_cookie(monkeypatch):
    """Refresh must rotate the cookie without exposing its secret."""
    monkeypatch.setenv("COOKIE_SECURE", "true")
    monkeypatch.setenv("REFRESH_TOKEN_EXPIRE_DAYS", "7")
    monkeypatch.delenv("AUTH_ALLOWED_ORIGINS", raising=False)

    monkeypatch.setattr(
        auth_routes,
        "refresh_session",
        lambda cookie: RefreshResult(
            access_token="new-access-jwt",
            refresh_token="new-refresh-secret",
            expires_in=900,
        ),
    )

    client = make_client()

    client.cookies.set(
        "refresh_token",
        "old-refresh-token",
        path="/auth",
    )

    response = client.post(
        "/auth/refresh",
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 200

    assert response.json() == {
        "access_token": "new-access-jwt",
        "token_type": "bearer",
        "expires_in": 900,
    }

    cookie_header = response.headers["set-cookie"].lower()

    assert "httponly" in cookie_header
    assert "secure" in cookie_header
    assert "samesite=strict" in cookie_header
    assert "path=/auth" in cookie_header
    assert "new-refresh-secret" not in response.text
    assert response.headers["cache-control"] == "no-store"


# =============================================================================
# MISSING OR INVALID CREDENTIALS
# =============================================================================

def test_missing_cookie_returns_401(monkeypatch):
    """Missing refresh credentials must not authenticate."""
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.delenv("AUTH_ALLOWED_ORIGINS", raising=False)

    monkeypatch.setattr(
        auth_routes,
        "refresh_session",
        lambda cookie: None,
    )

    response = make_client().post(
        "/auth/refresh",
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 401


def test_invalid_refresh_returns_401(monkeypatch):
    """Invalid refresh credentials must receive a generic 401."""
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.delenv("AUTH_ALLOWED_ORIGINS", raising=False)

    monkeypatch.setattr(
        auth_routes,
        "refresh_session",
        lambda cookie: None,
    )

    client = make_client()
    client.cookies.set(
        "refresh_token",
        "invalid-token",
        path="/auth",
    )

    response = client.post(
        "/auth/refresh",
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 401
    assert "set-cookie" not in response.headers


# =============================================================================
# ORIGIN PROTECTION
# =============================================================================

def test_cross_origin_refresh_is_rejected(monkeypatch):
    """Untrusted origins must be rejected before token rotation."""
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.delenv("AUTH_ALLOWED_ORIGINS", raising=False)

    refresh_calls = []

    def track_refresh(cookie):
        refresh_calls.append(cookie)
        return None

    monkeypatch.setattr(
        auth_routes,
        "refresh_session",
        track_refresh,
    )

    client = make_client()
    client.cookies.set(
        "refresh_token",
        "synthetic-token",
        path="/auth",
    )

    response = client.post(
        "/auth/refresh",
        headers={"Origin": "https://untrusted.example"},
    )

    assert response.status_code == 403
    assert refresh_calls == []


def test_missing_origin_signals_are_rejected(monkeypatch):
    """Requests without trusted browser signals fail closed."""
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.delenv("AUTH_ALLOWED_ORIGINS", raising=False)

    response = make_client().post("/auth/refresh")

    assert response.status_code == 403


def test_same_origin_fetch_metadata_is_accepted(monkeypatch):
    """Same-origin browser fetch metadata can authorize the request."""
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.delenv("AUTH_ALLOWED_ORIGINS", raising=False)

    monkeypatch.setattr(
        auth_routes,
        "refresh_session",
        lambda cookie: RefreshResult(
            access_token="new-jwt",
            refresh_token="new-secret",
            expires_in=900,
        ),
    )

    response = make_client().post(
        "/auth/refresh",
        headers={"Sec-Fetch-Site": "same-origin"},
    )

    assert response.status_code == 200


# =============================================================================
# SERVICE FAILURE
# =============================================================================

def test_refresh_service_failure_returns_503(monkeypatch):
    """Unexpected service errors must not expose internal details."""
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.delenv("AUTH_ALLOWED_ORIGINS", raising=False)

    def fail_refresh(cookie):
        raise RuntimeError("Synthetic database outage")

    monkeypatch.setattr(
        auth_routes,
        "refresh_session",
        fail_refresh,
    )

    client = make_client()
    client.cookies.set(
        "refresh_token",
        "synthetic-token",
        path="/auth",
    )

    response = client.post(
        "/auth/refresh",
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 503
    assert "Synthetic database outage" not in response.text
