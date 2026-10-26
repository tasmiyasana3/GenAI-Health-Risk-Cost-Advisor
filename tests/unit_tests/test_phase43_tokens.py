
"""Reusable unit tests for Phase 4.3A JWT access tokens.

Tests run without PostgreSQL, ChromaDB, Gemini or FastAPI.
A test-only signing secret is supplied using pytest monkeypatch.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest

from services.token_service import (
    JWT_ISSUER,
    TokenConfigurationError,
    TokenValidationError,
    create_access_token,
    verify_access_token,
)


@pytest.fixture
def jwt_test_environment(monkeypatch):
    """Configure a separate JWT secret for each test."""
    monkeypatch.setenv("JWT_SECRET_KEY", "a" * 64)
    monkeypatch.setenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "15")


def test_create_and_verify_access_token(jwt_test_environment):
    """A valid token must identify its user and session."""
    user_id = str(uuid4())
    session_id = str(uuid4())

    token, expires_in = create_access_token(
        user_id=user_id,
        session_id=session_id,
    )

    verified = verify_access_token(token)

    assert verified["user_id"] == user_id
    assert verified["session_id"] == session_id
    assert expires_in == 900


def test_expired_token_is_rejected(jwt_test_environment):
    """An expired token must not be accepted."""
    now = datetime.now(timezone.utc)

    expired_token = jwt.encode(
        {
            "sub": str(uuid4()),
            "sid": str(uuid4()),
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(hours=1),
            "iss": JWT_ISSUER,
            "token_type": "access",
        },
        "a" * 64,
        algorithm="HS256",
    )

    with pytest.raises(TokenValidationError):
        verify_access_token(expired_token)


def test_wrong_signing_secret_is_rejected(jwt_test_environment):
    """A token signed by another secret must fail verification."""
    now = datetime.now(timezone.utc)

    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "sid": str(uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=15),
            "iss": JWT_ISSUER,
            "token_type": "access",
        },
        "b" * 64,
        algorithm="HS256",
    )

    with pytest.raises(TokenValidationError):
        verify_access_token(token)


def test_invalid_session_id_is_rejected(jwt_test_environment):
    """A token with an invalid session identifier must fail."""
    with pytest.raises(ValueError):
        create_access_token(
            user_id=str(uuid4()),
            session_id="not-a-valid-uuid",
        )


def test_missing_secret_is_rejected(monkeypatch):
    """The service must never fall back to an unsafe secret."""
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

    with pytest.raises(TokenConfigurationError):
        create_access_token(
            user_id=str(uuid4()),
            session_id=str(uuid4()),
        )


def test_jwt_contains_no_sensitive_user_data(jwt_test_environment):
    """JWT payload must not contain credentials or policy content."""
    token, _ = create_access_token(
        user_id=str(uuid4()),
        session_id=str(uuid4()),
    )

    payload = jwt.decode(
        token,
        "a" * 64,
        algorithms=["HS256"],
        issuer=JWT_ISSUER,
    )

    assert "password" not in payload
    assert "password_hash" not in payload
    assert "email" not in payload
    assert "policy_content" not in payload
