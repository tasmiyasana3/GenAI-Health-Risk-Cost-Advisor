
"""
MODULE NAME
-----------
PHASE 4.3E LOGOUT SESSION UNIT TESTS

PURPOSE
-------
Verify logout-session behavior without PostgreSQL.

ENVIRONMENT / CONFIGURATION
---------------------------
No database connection required.

DEPENDENCIES
------------
pytest, unittest.mock, logout_session_service.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
Missing, malformed, valid, expired, revoked, unknown,
and mismatched refresh tokens.

SECURITY NOTES
--------------
A token must match the current stored hash before revocation.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from services.logout_session_service import logout_session


SESSION_ID = str(uuid4())
TOKEN_HASH = "a" * 64


def make_session(
    *,
    stored_hash=TOKEN_HASH,
    expired=False,
    revoked=False,
):
    """Build a representative session database row."""
    delta = timedelta(days=-1 if expired else 1)

    return {
        "refresh_token_hash": stored_hash,
        "expires_at": datetime.now(timezone.utc) + delta,
        "revoked_at": (
            datetime.now(timezone.utc) if revoked else None
        ),
    }


@contextmanager
def fake_database(row, update_result=None):
    """Provide mocked connection and cursor context managers."""
    cursor = MagicMock()
    cursor.fetchone.side_effect = [row, update_result]

    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor

    with patch(
        "services.logout_session_service.get_db_connection"
    ) as connection_factory:
        connection_factory.return_value.__enter__.return_value = (
            connection
        )
        yield cursor


def test_missing_cookie_returns_false():
    assert logout_session(None) is False


def test_malformed_cookie_returns_false():
    assert logout_session("not-a-refresh-token") is False


def test_unknown_session_returns_false():
    with (
        patch(
            "services.logout_session_service.parse_refresh_token",
            return_value=(SESSION_ID, "secret"),
        ),
        patch(
            "services.logout_session_service.hash_refresh_secret",
            return_value=TOKEN_HASH,
        ),
        fake_database(None) as cursor,
    ):
        assert logout_session("cookie") is False
        assert cursor.execute.call_count == 1


@pytest.mark.parametrize(
    "session",
    [
        make_session(expired=True),
        make_session(revoked=True),
        make_session(stored_hash="b" * 64),
    ],
)
def test_invalid_session_is_not_revoked(session):
    with (
        patch(
            "services.logout_session_service.parse_refresh_token",
            return_value=(SESSION_ID, "secret"),
        ),
        patch(
            "services.logout_session_service.hash_refresh_secret",
            return_value=TOKEN_HASH,
        ),
        fake_database(session) as cursor,
    ):
        assert logout_session("cookie") is False
        assert cursor.execute.call_count == 1


def test_current_token_revokes_session():
    with (
        patch(
            "services.logout_session_service.parse_refresh_token",
            return_value=(SESSION_ID, "secret"),
        ),
        patch(
            "services.logout_session_service.hash_refresh_secret",
            return_value=TOKEN_HASH,
        ),
        fake_database(
            make_session(),
            update_result={"session_id": SESSION_ID},
        ) as cursor,
    ):
        assert logout_session("cookie") is True
        assert cursor.execute.call_count == 2


def test_database_failure_propagates():
    with (
        patch(
            "services.logout_session_service.parse_refresh_token",
            return_value=(SESSION_ID, "secret"),
        ),
        patch(
            "services.logout_session_service.hash_refresh_secret",
            return_value=TOKEN_HASH,
        ),
        patch(
            "services.logout_session_service.get_db_connection",
            side_effect=RuntimeError("Database unavailable"),
        ),
    ):
        with pytest.raises(RuntimeError):
            logout_session("cookie")
