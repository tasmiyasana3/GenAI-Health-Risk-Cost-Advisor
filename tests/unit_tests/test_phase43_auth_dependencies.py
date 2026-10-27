
"""
MODULE NAME
-----------
PHASE 4.3F AUTHENTICATION DEPENDENCY TESTS

PURPOSE
-------
Verify protected-route authentication without PostgreSQL.

ENVIRONMENT / CONFIGURATION
---------------------------
Uses an isolated FastAPI application and mocked services.

DEPENDENCIES
------------
pytest, FastAPI, TestClient, unittest.mock.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Reject missing credentials.
2. Reject malformed or invalid credentials.
3. Accept valid JWTs with active sessions.
4. Reject revoked or expired sessions.
5. Reject user/session ownership mismatches.
6. Handle authentication infrastructure failures.

SECURITY NOTES
--------------
All protected routes must derive identity from verified JWT claims.
"""

from unittest.mock import patch
from uuid import uuid4

import pytest

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from api.auth_dependencies import (
    AuthenticatedUser,
    get_current_user,
)
from services.token_service import (
    TokenConfigurationError,
    TokenValidationError,
)


# =============================================================================
# TEST APPLICATION
# =============================================================================

USER_ID = str(uuid4())
SESSION_ID = str(uuid4())


@pytest.fixture
def client():
    """Create a test-only protected endpoint."""
    app = FastAPI()

    @app.get("/protected")
    def protected(
        current_user: AuthenticatedUser = Depends(get_current_user),
    ):
        return {
            "user_id": current_user.user_id,
            "session_id": current_user.session_id,
        }

    return TestClient(app)


def bearer_headers(token="example-jwt"):
    """Create a Bearer Authorization header."""
    return {"Authorization": f"Bearer {token}"}


def verified_identity():
    """Return representative verified JWT claims."""
    return {
        "user_id": USER_ID,
        "session_id": SESSION_ID,
    }


# =============================================================================
# AUTHENTICATION TESTS
# =============================================================================

def test_missing_token_returns_401(client):
    result = client.get("/protected")

    assert result.status_code == 401
    assert result.headers["www-authenticate"] == "Bearer"


def test_wrong_authorization_scheme_is_rejected(client):
    result = client.get(
        "/protected",
        headers={"Authorization": "Basic example"},
    )

    assert result.status_code == 401


def test_invalid_jwt_returns_401(client):
    with patch(
        "api.auth_dependencies.verify_access_token",
        side_effect=TokenValidationError("Invalid token"),
    ):
        result = client.get(
            "/protected",
            headers=bearer_headers(),
        )

    assert result.status_code == 401


def test_active_session_allows_access(client):
    with (
        patch(
            "api.auth_dependencies.verify_access_token",
            return_value=verified_identity(),
        ),
        patch(
            "api.auth_dependencies.is_session_active",
            return_value=True,
        ) as active_session,
    ):
        result = client.get(
            "/protected",
            headers=bearer_headers(),
        )

    assert result.status_code == 200
    assert result.json() == verified_identity()

    active_session.assert_called_once_with(
        session_id=SESSION_ID,
        user_id=USER_ID,
    )


@pytest.mark.parametrize(
    "active",
    [False],
)
def test_inactive_session_returns_401(client, active):
    with (
        patch(
            "api.auth_dependencies.verify_access_token",
            return_value=verified_identity(),
        ),
        patch(
            "api.auth_dependencies.is_session_active",
            return_value=active,
        ),
    ):
        result = client.get(
            "/protected",
            headers=bearer_headers(),
        )

    assert result.status_code == 401


def test_session_ownership_mismatch_is_rejected(client):
    """The database must reject a session belonging to another user."""
    with (
        patch(
            "api.auth_dependencies.verify_access_token",
            return_value=verified_identity(),
        ),
        patch(
            "api.auth_dependencies.is_session_active",
            return_value=False,
        ) as check,
    ):
        result = client.get(
            "/protected",
            headers=bearer_headers(),
        )

    assert result.status_code == 401

    check.assert_called_once_with(
        session_id=SESSION_ID,
        user_id=USER_ID,
    )


def test_jwt_configuration_failure_returns_503(client):
    with patch(
        "api.auth_dependencies.verify_access_token",
        side_effect=TokenConfigurationError("Missing secret"),
    ):
        result = client.get(
            "/protected",
            headers=bearer_headers(),
        )

    assert result.status_code == 503


def test_database_failure_returns_503(client):
    with (
        patch(
            "api.auth_dependencies.verify_access_token",
            return_value=verified_identity(),
        ),
        patch(
            "api.auth_dependencies.is_session_active",
            side_effect=RuntimeError("Database unavailable"),
        ),
    ):
        result = client.get(
            "/protected",
            headers=bearer_headers(),
        )

    assert result.status_code == 503
