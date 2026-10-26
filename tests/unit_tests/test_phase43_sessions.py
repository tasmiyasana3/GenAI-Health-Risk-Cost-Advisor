
"""Unit tests for Phase 4.3B session database operations.

No live PostgreSQL connection is required.
Database integration tests are run separately against the isolated
health_rag_migration_test database.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from services.session_database_service import (
    _validate_expiry,
    _validate_token_hash,
    _validate_uuid,
    create_session,
    rotate_session_token,
)


def future_expiry():
    """Return a valid future expiration timestamp."""
    return datetime.now(timezone.utc) + timedelta(days=7)


def test_valid_uuid():
    value = uuid4()
    assert _validate_uuid(str(value)) == value


def test_invalid_uuid():
    with pytest.raises(ValueError):
        _validate_uuid("invalid-session-id")


def test_valid_token_hash():
    digest = "a" * 64
    assert _validate_token_hash(digest) == digest


@pytest.mark.parametrize(
    "invalid_hash",
    [
        "",
        "abc",
        "A" * 64,
        "z" * 64,
        None,
    ],
)
def test_invalid_token_hash(invalid_hash):
    with pytest.raises(ValueError):
        _validate_token_hash(invalid_hash)


def test_valid_future_expiry():
    expiry = future_expiry()
    assert _validate_expiry(expiry) == expiry


def test_naive_expiry_rejected():
    with pytest.raises(ValueError):
        _validate_expiry(datetime.now())


def test_past_expiry_rejected():
    past = datetime.now(timezone.utc) - timedelta(days=1)

    with pytest.raises(ValueError):
        _validate_expiry(past)


def test_create_session_rejects_invalid_user_id():
    with pytest.raises(ValueError):
        create_session(
            user_id="not-a-uuid",
            refresh_token_hash="a" * 64,
            expires_at=future_expiry(),
        )


def test_create_session_rejects_invalid_hash():
    with pytest.raises(ValueError):
        create_session(
            user_id=str(uuid4()),
            refresh_token_hash="invalid",
            expires_at=future_expiry(),
        )


def test_rotation_requires_new_hash():
    with pytest.raises(ValueError):
        rotate_session_token(
            session_id=str(uuid4()),
            expected_token_hash="a" * 64,
            new_token_hash="a" * 64,
            new_expires_at=future_expiry(),
        )
