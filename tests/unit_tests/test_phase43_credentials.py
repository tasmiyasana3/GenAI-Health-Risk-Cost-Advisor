
"""Phase 4.3A tests for password-based account authentication.

Database queries are replaced with test doubles so these tests do not
connect to PostgreSQL or modify real user accounts.
"""

from uuid import uuid4

import pytest

from services import auth_service


TEST_USER_ID = str(uuid4())
TEST_EMAIL = "phase43@example.com"
TEST_PASSWORD = "ValidPassword123!"


@pytest.fixture
def stored_user():
    """Create a simulated account with a real Argon2id hash."""
    return {
        "user_id": TEST_USER_ID,
        "email": TEST_EMAIL,
        "password_hash": auth_service.hash_password(
            TEST_PASSWORD
        ),
    }


def test_valid_credentials_return_user_id(
    monkeypatch,
    stored_user,
):
    """A correct email and password must authenticate."""

    monkeypatch.setattr(
        auth_service,
        "get_user_by_email",
        lambda email: stored_user,
    )

    result = auth_service.authenticate_user(
        TEST_EMAIL,
        TEST_PASSWORD,
    )

    assert result == TEST_USER_ID


def test_incorrect_password_is_rejected(
    monkeypatch,
    stored_user,
):
    """A wrong password must not authenticate."""

    monkeypatch.setattr(
        auth_service,
        "get_user_by_email",
        lambda email: stored_user,
    )

    result = auth_service.authenticate_user(
        TEST_EMAIL,
        "IncorrectPassword123!",
    )

    assert result is None


def test_unknown_email_is_rejected(monkeypatch):
    """An unknown email must not authenticate."""

    monkeypatch.setattr(
        auth_service,
        "get_user_by_email",
        lambda email: None,
    )

    result = auth_service.authenticate_user(
        "unknown@example.com",
        TEST_PASSWORD,
    )

    assert result is None


def test_corrupted_hash_is_rejected(monkeypatch):
    """A malformed password hash must not authenticate."""

    monkeypatch.setattr(
        auth_service,
        "get_user_by_email",
        lambda email: {
            "user_id": TEST_USER_ID,
            "email": email,
            "password_hash": "invalid-hash",
        },
    )

    result = auth_service.authenticate_user(
        TEST_EMAIL,
        TEST_PASSWORD,
    )

    assert result is None


def test_oversized_password_is_rejected(monkeypatch):
    """An oversized password must be rejected before database access."""

    def unexpected_database_call(email):
        pytest.fail(
            "Database should not be queried for oversized passwords."
        )

    monkeypatch.setattr(
        auth_service,
        "get_user_by_email",
        unexpected_database_call,
    )

    result = auth_service.authenticate_user(
        TEST_EMAIL,
        "x" * 1025,
    )

    assert result is None


def test_invalid_input_types_are_rejected(monkeypatch):
    """Non-string inputs must not trigger a database query."""

    def unexpected_database_call(email):
        pytest.fail("Database should not be queried.")

    monkeypatch.setattr(
        auth_service,
        "get_user_by_email",
        unexpected_database_call,
    )

    assert auth_service.authenticate_user(
        None,
        TEST_PASSWORD,
    ) is None

    assert auth_service.authenticate_user(
        TEST_EMAIL,
        None,
    ) is None
