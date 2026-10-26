
"""Phase 4.3B: PostgreSQL session integration tests.

PURPOSE
-------
Verify that the authentication session service works with a real
PostgreSQL database.

Unlike test_phase43_sessions.py, which tests Python input validation,
this file verifies actual database operations, transactions,
constraints, and persistence.

TEST DATABASE
-------------
All tests must use:
    health_rag_migration_test (isolated test database)

Never use:
    health_rag_db (working application database)

The existing safe_test_database fixture:
1. Requires RUN_PHASE4_DB_TESTS=1.
2. Temporarily sets DB_NAME to the isolated test database.
3. Verifies the actual PostgreSQL database connection.
4. Verifies the database-owner cleanup connection.
5. Restores environment variables after testing.

WHAT WE TEST
------------
1. Session creation and retrieval.
2. Active-session verification.
3. Rejection of incorrect session ownership.
4. Atomic refresh-token rotation.
5. Preservation of consumed refresh-token hashes.
6. Rejection of repeated rotation with an old token.
7. Session revocation and repeated logout behavior.
8. Expired-session rejection.
9. Foreign-key enforcement for nonexistent users.
10. Existence of the refresh-token history table.
11. Storage of consumed token hashes.
12. Transaction rollback when token-history insertion fails.

SECURITY NOTES
--------------
- These tests use synthetic token hashes, not real credentials.
- No plaintext refresh tokens are stored.
- Test users are deleted after each test.
- Session and history records are removed through ON DELETE CASCADE.
- Token replay classification and HTTP responses are tested later.
"""

import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest

from services.database_service import (
    create_user,
    get_db_connection,
)

from services.session_database_service import (
    create_session,
    get_session,
    is_session_active,
    revoke_session,
    rotate_session_token,
)


# ---------------------------------------------------------------------
# TEST CONFIGURATION
# ---------------------------------------------------------------------

TEST_DATABASE = "health_rag_migration_test"

# The owner role can delete temporary users during cleanup.
# The application role intentionally has more restricted permissions.
TEST_DATABASE_OWNER = "tasmiyasana"


# ---------------------------------------------------------------------
# TEST HELPERS
# ---------------------------------------------------------------------

def future_expiry() -> datetime:
    """Return a timezone-aware expiry seven days from now.

    A future expiry represents a valid, nonexpired login session.
    """
    return datetime.now(timezone.utc) + timedelta(days=7)


def unique_token_hash() -> str:
    """Generate a unique synthetic SHA-256-shaped token hash.

    secrets.token_hex(32) produces 64 lowercase hexadecimal
    characters, matching the expected database column format.

    These are test values, not actual refresh tokens.
    """
    return secrets.token_hex(32)


# ---------------------------------------------------------------------
# SHARED TEST FIXTURE
# ---------------------------------------------------------------------

@pytest.fixture
def temporary_user(safe_test_database):
    """Create a temporary user and clean it up after the test.

    The safe_test_database fixture executes first, ensuring
    that the application is connected to the isolated test DB.

    Each test receives a unique user so that:
    - Tests do not share session records.
    - Tests can run repeatedly.
    - Existing application accounts remain untouched.

    Cleanup is performed using the verified database-owner role.

    Deleting the user also removes:
    - Related user_sessions rows.
    - Related refresh_token_history rows.

    This happens through PostgreSQL foreign-key ON DELETE CASCADE.
    """

    # A unique email avoids collisions across repeated test runs.
    email = f"phase43-session-{uuid4().hex}@example.com"

    # Create the user through the actual application database service.
    user = create_user(
        email=email,
        password_hash="integration-test-placeholder",
    )

    user_id = user["user_id"]

    try:
        # Hand the temporary user ID to the test.
        yield user_id

    finally:
        # The application role does not need permission to delete users.
        # Cleanup uses the local database owner instead.
        with psycopg.connect(
            dbname=TEST_DATABASE,
            user=TEST_DATABASE_OWNER,
        ) as connection:

            # Verify the destination again before executing DELETE.
            actual_database = connection.execute(
                "SELECT current_database()"
            ).fetchone()[0]

            if actual_database != TEST_DATABASE:
                raise RuntimeError(
                    "Unsafe database connection during test cleanup."
                )

            connection.execute(
                """
                DELETE FROM public.users
                WHERE user_id = %s
                """,
                (user_id,),
            )


# ---------------------------------------------------------------------
# TEST 1: CREATE AND RETRIEVE A SESSION
# ---------------------------------------------------------------------

def test_session_creation_and_retrieval(temporary_user):
    """Verify that a session is stored and can be retrieved."""

    token_hash = unique_token_hash()

    session = create_session(
        user_id=str(temporary_user),
        refresh_token_hash=token_hash,
        expires_at=future_expiry(),
    )

    # Fetch the session using a separate database operation.
    stored_session = get_session(
        str(session["session_id"])
    )

    assert stored_session is not None

    # Session ownership must match the registered user.
    assert stored_session["user_id"] == temporary_user

    # A new session should not be revoked.
    assert stored_session["revoked_at"] is None

    # Public session metadata must not expose refresh-token hashes.
    assert "refresh_token_hash" not in stored_session


# ---------------------------------------------------------------------
# TEST 2: NEW SESSION IS ACTIVE
# ---------------------------------------------------------------------

def test_new_session_is_active(temporary_user):
    """Verify that a new, unexpired session is active."""

    session = create_session(
        user_id=str(temporary_user),
        refresh_token_hash=unique_token_hash(),
        expires_at=future_expiry(),
    )

    active = is_session_active(
        session_id=str(session["session_id"]),
        user_id=str(temporary_user),
    )

    assert active is True


# ---------------------------------------------------------------------
# TEST 3: SESSION OWNERSHIP
# ---------------------------------------------------------------------

def test_session_rejects_wrong_user(temporary_user):
    """A session must not authenticate a different user."""

    session = create_session(
        user_id=str(temporary_user),
        refresh_token_hash=unique_token_hash(),
        expires_at=future_expiry(),
    )

    # Simulate another user's UUID.
    unrelated_user_id = str(uuid4())

    active = is_session_active(
        session_id=str(session["session_id"]),
        user_id=unrelated_user_id,
    )

    assert active is False


# ---------------------------------------------------------------------
# TEST 4: ATOMIC TOKEN ROTATION AND HISTORY
# ---------------------------------------------------------------------

def test_refresh_hash_rotation_records_history(temporary_user):
    """Verify successful rotation and consumed-token recording.

    The service must perform both operations in one transaction:

    1. Insert the old token hash into refresh_token_history.
    2. Replace the current hash in user_sessions.

    The old token must not be accepted for another rotation.
    """

    original_hash = unique_token_hash()
    replacement_hash = unique_token_hash()

    session = create_session(
        user_id=str(temporary_user),
        refresh_token_hash=original_hash,
        expires_at=future_expiry(),
    )

    session_id = str(session["session_id"])

    # First use of the current refresh-token hash.
    rotation_succeeded = rotate_session_token(
        session_id=session_id,
        expected_token_hash=original_hash,
        new_token_hash=replacement_hash,
        new_expires_at=future_expiry(),
    )

    assert rotation_succeeded is True

    # Inspect both database tables after the transaction commits.
    with get_db_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT refresh_token_hash, rotated_at
                FROM public.user_sessions
                WHERE session_id = %s
                """,
                (session["session_id"],),
            )

            current_session = cursor.fetchone()

            cursor.execute(
                """
                SELECT token_hash, consumed_at
                FROM public.refresh_token_history
                WHERE session_id = %s
                """,
                (session["session_id"],),
            )

            consumed_token = cursor.fetchone()

    # PostgreSQL CHAR(64) may be padded, so strip whitespace.
    assert current_session["refresh_token_hash"].strip() == (
        replacement_hash
    )

    assert current_session["rotated_at"] is not None

    assert consumed_token is not None

    assert consumed_token["token_hash"].strip() == original_hash

    assert consumed_token["consumed_at"] is not None

    # Attempting to reuse the original hash must not rotate again.
    repeated_rotation = rotate_session_token(
        session_id=session_id,
        expected_token_hash=original_hash,
        new_token_hash=unique_token_hash(),
        new_expires_at=future_expiry(),
    )

    assert repeated_rotation is False


# ---------------------------------------------------------------------
# TEST 5: SESSION REVOCATION
# ---------------------------------------------------------------------

def test_session_revocation(temporary_user):
    """Verify that logout-style revocation disables a session."""

    session = create_session(
        user_id=str(temporary_user),
        refresh_token_hash=unique_token_hash(),
        expires_at=future_expiry(),
    )

    session_id = str(session["session_id"])

    # First revocation changes the session state.
    assert revoke_session(session_id) is True

    # The session must no longer be active.
    assert is_session_active(
        session_id=session_id,
        user_id=str(temporary_user),
    ) is False

    # Repeated revocation must not modify the session again.
    assert revoke_session(session_id) is False


# ---------------------------------------------------------------------
# TEST 6: EXPIRED SESSION
# ---------------------------------------------------------------------

def test_expired_session_is_inactive(temporary_user):
    """Verify that an expired session cannot authenticate."""

    session = create_session(
        user_id=str(temporary_user),
        refresh_token_hash=unique_token_hash(),
        expires_at=future_expiry(),
    )

    # Simulate expiry directly in the isolated test database.
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

    active = is_session_active(
        session_id=str(session["session_id"]),
        user_id=str(temporary_user),
    )

    assert active is False


# ---------------------------------------------------------------------
# TEST 7: FOREIGN-KEY PROTECTION
# ---------------------------------------------------------------------

def test_nonexistent_user_cannot_create_session(
    safe_test_database,
):
    """A session cannot reference a user who does not exist."""

    nonexistent_user_id = str(uuid4())

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        create_session(
            user_id=nonexistent_user_id,
            refresh_token_hash=unique_token_hash(),
            expires_at=future_expiry(),
        )


# ---------------------------------------------------------------------
# TEST 8: REFRESH HISTORY TABLE EXISTS
# ---------------------------------------------------------------------

def test_refresh_history_table_exists(safe_test_database):
    """Verify that migration 006 created the required table."""

    with get_db_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT to_regclass(
                    'public.refresh_token_history'
                ) AS table_name
                """
            )

            result = cursor.fetchone()

    assert result["table_name"] is not None


# ---------------------------------------------------------------------
# TEST 9: CONSUMED TOKEN HASH STORAGE
# ---------------------------------------------------------------------

def test_consumed_hash_history_storage(temporary_user):
    """Verify that consumed-token hashes can be persisted."""

    session = create_session(
        user_id=str(temporary_user),
        refresh_token_hash=unique_token_hash(),
        expires_at=future_expiry(),
    )

    consumed_hash = unique_token_hash()

    with get_db_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO public.refresh_token_history (
                    token_hash,
                    session_id
                )
                VALUES (%s, %s)
                """,
                (
                    consumed_hash,
                    session["session_id"],
                ),
            )

            cursor.execute(
                """
                SELECT token_hash, session_id
                FROM public.refresh_token_history
                WHERE token_hash = %s
                """,
                (consumed_hash,),
            )

            stored = cursor.fetchone()

    assert stored is not None

    assert stored["token_hash"].strip() == consumed_hash

    assert stored["session_id"] == session["session_id"]


# ---------------------------------------------------------------------
# TEST 10: TRANSACTION ROLLBACK
# ---------------------------------------------------------------------

def test_rotation_rolls_back_when_history_insert_fails(
    temporary_user,
):
    """Verify that failed history insertion cannot rotate a token.

    This tests a critical transactional guarantee.

    We deliberately insert the current token hash into history
    before rotation.

    When rotation tries to insert the same hash again, PostgreSQL
    must raise UniqueViolation.

    The transaction must roll back, preserving the original
    current token hash.
    """

    original_hash = unique_token_hash()
    replacement_hash = unique_token_hash()

    session = create_session(
        user_id=str(temporary_user),
        refresh_token_hash=original_hash,
        expires_at=future_expiry(),
    )

    session_id = str(session["session_id"])

    # Prepare a controlled uniqueness conflict in the test database.
    with get_db_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO public.refresh_token_history (
                    token_hash,
                    session_id
                )
                VALUES (%s, %s)
                """,
                (
                    original_hash,
                    session["session_id"],
                ),
            )

    # The history insert inside rotate_session_token must fail.
    with pytest.raises(psycopg.errors.UniqueViolation):
        rotate_session_token(
            session_id=session_id,
            expected_token_hash=original_hash,
            new_token_hash=replacement_hash,
            new_expires_at=future_expiry(),
        )

    # Verify the failed transaction did not update the session.
    with get_db_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT refresh_token_hash, rotated_at
                FROM public.user_sessions
                WHERE session_id = %s
                """,
                (session["session_id"],),
            )

            stored = cursor.fetchone()

    assert stored["refresh_token_hash"].strip() == original_hash

    assert stored["rotated_at"] is None
