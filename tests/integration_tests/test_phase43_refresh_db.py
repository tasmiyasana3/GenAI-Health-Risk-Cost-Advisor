
"""
MODULE NAME
-----------
PHASE 4.3D REFRESH DATABASE INTEGRATION TESTS

PURPOSE
-------
Verify replay-aware refresh-token rotation using PostgreSQL.

ENVIRONMENT / CONFIGURATION
---------------------------
Requires RUN_PHASE4_DB_TESTS=1.

Uses the existing safe_test_database fixture and the isolated
health_rag_migration_test database.

DEPENDENCIES
------------
pytest, psycopg, concurrent.futures, threading,
services.database_service,
services.session_database_service.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Successful refresh-token rotation.
2. Consumed-token replay detection and session revocation.
3. Rejection of unrelated incorrect tokens.
4. Rejection of expired sessions.
5. Concurrent refresh requests cannot both succeed.

SECURITY NOTES
--------------
Only synthetic token hashes are used.
Cleanup is restricted to the isolated test database.
Never execute these tests against production data.
"""

import secrets

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest

from services.database_service import (
    create_user,
    get_db_connection,
)

from services.session_database_service import (
    RefreshRotationStatus,
    create_session,
    get_session,
    rotate_session_token_checked,
)


# =============================================================================
# TEST CONFIGURATION
# =============================================================================

TEST_DATABASE = "health_rag_migration_test"
TEST_DATABASE_OWNER = "tasmiyasana"


# =============================================================================
# TEST HELPERS
# =============================================================================

def unique_token_hash() -> str:
    """Generate a unique synthetic 64-character token hash."""
    return secrets.token_hex(32)


def future_expiry() -> datetime:
    """Return a timezone-aware expiration seven days from now."""
    return datetime.now(timezone.utc) + timedelta(days=7)


# =============================================================================
# ISOLATED TEST USER
# =============================================================================

@pytest.fixture
def temporary_user(safe_test_database):
    """Create a synthetic user and safely remove it after testing."""
    user = create_user(
        email=f"phase43-refresh-{uuid4().hex}@example.com",
        password_hash="integration-test-placeholder",
    )

    user_id = user["user_id"]

    try:
        yield user_id

    finally:
        # The restricted application role cannot delete users.
        # Cleanup uses the verified local database-owner role.
        with psycopg.connect(
            dbname=TEST_DATABASE,
            user=TEST_DATABASE_OWNER,
        ) as connection:

            actual_database = connection.execute(
                "SELECT current_database()"
            ).fetchone()[0]

            if actual_database != TEST_DATABASE:
                raise RuntimeError(
                    "Unsafe integration test cleanup destination."
                )

            connection.execute(
                """
                DELETE FROM public.users
                WHERE user_id = %s
                """,
                (user_id,),
            )


# =============================================================================
# SUCCESSFUL ROTATION AND REPLAY
# =============================================================================

def test_rotation_and_replay_revokes_session(temporary_user):
    """A consumed refresh token must not be reusable."""
    original_hash = unique_token_hash()
    replacement_hash = unique_token_hash()
    third_hash = unique_token_hash()

    session = create_session(
        user_id=str(temporary_user),
        refresh_token_hash=original_hash,
        expires_at=future_expiry(),
    )

    session_id = str(session["session_id"])

    # First use: the current token rotates successfully.
    status, user_id = rotate_session_token_checked(
        session_id=session_id,
        expected_token_hash=original_hash,
        new_token_hash=replacement_hash,
        new_expires_at=future_expiry(),
    )

    assert status == RefreshRotationStatus.ROTATED
    assert user_id == str(temporary_user)

    # Second use: the original token is already consumed.
    status, user_id = rotate_session_token_checked(
        session_id=session_id,
        expected_token_hash=original_hash,
        new_token_hash=third_hash,
        new_expires_at=future_expiry(),
    )

    assert status == RefreshRotationStatus.REPLAYED
    assert user_id is None

    stored_session = get_session(session_id)
    assert stored_session["revoked_at"] is not None

    # The replacement token is also unusable after revocation.
    status, _ = rotate_session_token_checked(
        session_id=session_id,
        expected_token_hash=replacement_hash,
        new_token_hash=third_hash,
        new_expires_at=future_expiry(),
    )

    assert status == RefreshRotationStatus.INVALID


# =============================================================================
# UNRELATED INVALID TOKEN
# =============================================================================

def test_unknown_token_does_not_revoke_session(temporary_user):
    """A random incorrect token must not revoke an active session."""
    current_hash = unique_token_hash()
    unknown_hash = unique_token_hash()
    replacement_hash = unique_token_hash()

    session = create_session(
        user_id=str(temporary_user),
        refresh_token_hash=current_hash,
        expires_at=future_expiry(),
    )

    session_id = str(session["session_id"])

    status, _ = rotate_session_token_checked(
        session_id=session_id,
        expected_token_hash=unknown_hash,
        new_token_hash=replacement_hash,
        new_expires_at=future_expiry(),
    )

    assert status == RefreshRotationStatus.INVALID
    assert get_session(session_id)["revoked_at"] is None

    # The legitimate current token should still work.
    status, _ = rotate_session_token_checked(
        session_id=session_id,
        expected_token_hash=current_hash,
        new_token_hash=replacement_hash,
        new_expires_at=future_expiry(),
    )

    assert status == RefreshRotationStatus.ROTATED


# =============================================================================
# EXPIRED SESSION
# =============================================================================

def test_expired_session_cannot_rotate(temporary_user):
    """Expired sessions must reject refresh attempts."""
    current_hash = unique_token_hash()

    session = create_session(
        user_id=str(temporary_user),
        refresh_token_hash=current_hash,
        expires_at=future_expiry(),
    )

    session_id = str(session["session_id"])

    # Simulate expiration in the isolated database.
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE public.user_sessions
                SET expires_at = CURRENT_TIMESTAMP
                WHERE session_id = %s
                """,
                (session["session_id"],),
            )

    status, _ = rotate_session_token_checked(
        session_id=session_id,
        expected_token_hash=current_hash,
        new_token_hash=unique_token_hash(),
        new_expires_at=future_expiry(),
    )

    assert status == RefreshRotationStatus.INVALID


# =============================================================================
# CONCURRENT ROTATION
# =============================================================================

def test_concurrent_refresh_cannot_both_succeed(temporary_user):
    """Two competing uses of one refresh token cannot both rotate."""
    current_hash = unique_token_hash()

    session = create_session(
        user_id=str(temporary_user),
        refresh_token_hash=current_hash,
        expires_at=future_expiry(),
    )

    session_id = str(session["session_id"])

    # Synchronize both workers so they attempt rotation together.
    barrier = Barrier(2)

    def attempt_rotation() -> RefreshRotationStatus:
        replacement_hash = unique_token_hash()

        barrier.wait(timeout=10)

        status, _ = rotate_session_token_checked(
            session_id=session_id,
            expected_token_hash=current_hash,
            new_token_hash=replacement_hash,
            new_expires_at=future_expiry(),
        )

        return status

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(attempt_rotation)
            for _ in range(2)
        ]

        statuses = [
            future.result(timeout=20)
            for future in futures
        ]

    # One request rotates. The second sees a consumed token.
    assert statuses.count(RefreshRotationStatus.ROTATED) == 1
    assert statuses.count(RefreshRotationStatus.REPLAYED) == 1

    # Under the strict replay policy, the session is revoked.
    assert get_session(session_id)["revoked_at"] is not None
