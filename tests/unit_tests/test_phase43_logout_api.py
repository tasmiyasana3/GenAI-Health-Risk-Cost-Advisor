
"""
MODULE NAME
-----------
PHASE 4.3E LOGOUT API UNIT TESTS

PURPOSE
-------
Test HTTP logout behavior without a database.

ENVIRONMENT / CONFIGURATION
---------------------------
Uses FastAPI TestClient and monkeypatched cookie settings.

DEPENDENCIES
------------
pytest, FastAPI, TestClient, api.auth_routes.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Successful logout.
2. Missing-cookie logout.
3. Cookie deletion attributes.
4. Cross-origin rejection.
5. Infrastructure failure handling.

SECURITY NOTES
--------------
Logout must not silently succeed after a database failure.
"""

from unittest.mock import patch

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth_routes import router


@pytest.fixture
def client(monkeypatch):
    """Build an isolated authentication API test client."""
    monkeypatch.setenv("COOKIE_SECURE", "true")
    monkeypatch.delenv("AUTH_ALLOWED_ORIGINS", raising=False)

    app = FastAPI()
    app.include_router(router)

    return TestClient(app)


def test_logout_revokes_session_and_clears_cookie(client):
    with patch(
        "api.auth_routes.logout_session",
        return_value=True,
    ) as revoke:
        result = client.post(
            "/auth/logout",
            headers={
                "Origin": "http://testserver",
                "Cookie": "refresh_token=example-token",
            },
        )

    assert result.status_code == 200
    assert result.json() == {
        "message": "Logged out successfully."
    }

    revoke.assert_called_once_with("example-token")

    cookie = result.headers["set-cookie"].lower()

    assert "refresh_token=" in cookie
    assert "max-age=0" in cookie
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=strict" in cookie
    assert "path=/auth" in cookie
    assert result.headers["cache-control"] == "no-store"


def test_logout_without_cookie_is_idempotent(client):
    with patch(
        "api.auth_routes.logout_session",
        return_value=False,
    ) as revoke:
        result = client.post(
            "/auth/logout",
            headers={"Origin": "http://testserver"},
        )

    assert result.status_code == 200
    revoke.assert_called_once_with(None)
    assert "refresh_token=" in result.headers["set-cookie"]


def test_cross_origin_logout_is_rejected(client):
    with patch("api.auth_routes.logout_session") as revoke:
        result = client.post(
            "/auth/logout",
            headers={"Origin": "https://untrusted.example"},
        )

    assert result.status_code == 403
    revoke.assert_not_called()


def test_missing_origin_signals_are_rejected(client):
    with patch("api.auth_routes.logout_session") as revoke:
        result = client.post("/auth/logout")

    assert result.status_code == 403
    revoke.assert_not_called()


def test_same_origin_fetch_metadata_is_accepted(client):
    with patch(
        "api.auth_routes.logout_session",
        return_value=False,
    ):
        result = client.post(
            "/auth/logout",
            headers={"Sec-Fetch-Site": "same-origin"},
        )

    assert result.status_code == 200


def test_database_failure_returns_503(client):
    with patch(
        "api.auth_routes.logout_session",
        side_effect=RuntimeError("Database unavailable"),
    ):
        result = client.post(
            "/auth/logout",
            headers={"Origin": "http://testserver"},
        )

    assert result.status_code == 503
    assert "set-cookie" not in result.headers


def test_invalid_cookie_configuration_returns_503(
    client,
    monkeypatch,
):
    monkeypatch.setenv("COOKIE_SECURE", "invalid")

    with patch("api.auth_routes.logout_session") as revoke:
        result = client.post(
            "/auth/logout",
            headers={"Origin": "http://testserver"},
        )

    assert result.status_code == 503
    revoke.assert_not_called()
