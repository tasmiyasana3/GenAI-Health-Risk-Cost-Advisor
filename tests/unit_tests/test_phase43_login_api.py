
"""
PHASE 4.3C LOGIN API TESTS

PURPOSE
-------
Verify FastAPI login responses and cookie security settings.

ENVIRONMENT / CONFIGURATION
---------------------------
Uses a test-only FastAPI application with the authentication router.
PostgreSQL calls are replaced by test doubles.

DEPENDENCIES
------------
FastAPI TestClient, pytest, auth_routes, and LoginResult.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
Successful login, invalid credentials, refresh-cookie attributes,
response secrecy, and invalid cookie configuration.

SECURITY NOTES
--------------
No production credentials or real database connections are used.
"""

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import auth_routes
from services.login_service import LoginResult


def make_client() -> TestClient:
    """Create a minimal API containing authentication routes."""
    application = FastAPI()
    application.include_router(auth_routes.router)
    return TestClient(application)


def test_successful_login_sets_http_only_cookie(monkeypatch):
    """Login must return a JWT without exposing the refresh token."""
    monkeypatch.setenv("COOKIE_SECURE", "true")
    monkeypatch.setenv("REFRESH_TOKEN_EXPIRE_DAYS", "7")

    monkeypatch.setattr(
        auth_routes,
        "login_user",
        lambda email, password: LoginResult(
            access_token="synthetic-access-jwt",
            refresh_token="synthetic-refresh-token",
            expires_in=900,
            session_id=str(uuid4()),
        ),
    )

    response = make_client().post(
        "/auth/login",
        json={
            "email": "user@example.com",
            "password": "SyntheticPassword123!",
        },
    )

    assert response.status_code == 200

    assert response.json() == {
        "access_token": "synthetic-access-jwt",
        "token_type": "bearer",
        "expires_in": 900,
    }

    cookie = response.headers["set-cookie"].lower()

    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=strict" in cookie
    assert "path=/auth" in cookie
    assert "synthetic-refresh-token" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_invalid_credentials_return_401(monkeypatch):
    """Invalid credentials must return a generic error."""
    monkeypatch.setenv("COOKIE_SECURE", "false")

    monkeypatch.setattr(
        auth_routes,
        "login_user",
        lambda email, password: None,
    )

    response = make_client().post(
        "/auth/login",
        json={
            "email": "unknown@example.com",
            "password": "IncorrectPassword123!",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."
    assert "set-cookie" not in response.headers


def test_invalid_cookie_configuration_blocks_login(monkeypatch):
    """Invalid cookie settings must prevent authentication."""
    monkeypatch.setenv("COOKIE_SECURE", "invalid")

    response = make_client().post(
        "/auth/login",
        json={
            "email": "user@example.com",
            "password": "SyntheticPassword123!",
        },
    )

    assert response.status_code == 503
    assert "set-cookie" not in response.headers
