
"""
MODULE NAME
-----------
PHASE 4.3E LOGOUT DATABASE INTEGRATION TESTS

PURPOSE
-------
Verify secure logout and session revocation using real PostgreSQL
transactions.

ENVIRONMENT / CONFIGURATION
---------------------------
Requires:
    RUN_PHASE4_DB_TESTS=1

Database:
    health_rag_migration_test

The existing safe_test_database fixture verifies the actual
PostgreSQL connection before test records are created.

DEPENDENCIES
------------
pytest
psycopg
services.database_service
services.session_database_service
services.refresh_token_service
services.logout_session_service
services.refresh_session_service

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Valid logout revokes the correct PostgreSQL session.
2. A revoked session cannot refresh its access token.
3. An incorrect refresh secret cannot revoke a session.
4. Repeated logout is handled safely.
5. Expired sessions cannot be logged out again.
6. Logout affects only the intended session.

SECURITY NOTES
--------------
- Never execute these tests against the working application database.
- Use only synthetic users and cryptographically generated tokens.
- Store only refresh-secret hashes in PostgreSQL.
- Verify database isolation before creating test data.
- Clean up temporary users using the verified test database owner.
- Never log plaintext refresh tokens or secrets.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest

from services.database_service import (
    create_user,
    get_db_connection,
)

from services.logout_session_service import logout_session
from services.refresh_session_service import refresh_session

from services.refresh_token_service import (
    build_refresh_token,
    generate_refresh_secret,
    hash_refresh_secret,
)

from services.session_database_service import (
    create_session,
    get_session,
    is_session_active,
)


# =============================================================================
# TEST CONFIGURATION
# =============================================================================

TEST_DATABASE = "health_rag_migration_test"
TEST_DATABASE_OWNER = "tasmiyasana"


# =============================================================================
# TEST HELPERS
# =============================================================================

def future_expiry() -> datetime:
    """Return a timezone-aware expiration seven days from now."""
    return datetime.now(timezone.utc) + timedelta(days=7)


def create_test_refresh_session(user_id: str) -> tuple[str, str]:
    """
    Create a real PostgreSQL session and its matching refresh token.

    Parameters
    ----------
    user_id:
        UUID of the temporary test user.

    Returns
    -------
    tuple[str, str]:
        Session UUID and plaintext refresh token.

    Security
    --------
    The refresh secret is generated cryptographically.
    Only its SHA-256 hash is persisted in PostgreSQL.
    """
    # STEP 1: Generate a secure refresh secret.
    secret = generate_refresh_secret()

    # STEP 2: Store only the secret hash in PostgreSQL.
    session = create_session(
        user_id=str(user_id),
        refresh_token_hash=hash_refresh_secret(secret),
        expires_at=future_expiry(),
    )

    session_id = str(session["session_id"])

    # STEP 3: Construct the refresh token using the real session UUID.
    refresh_token = build_refresh_token(
        session_id=session_id,
        secret=secret,
    )

    return session_id, refresh_token


# =============================================================================
# ISOLATED TEST USER FIXTURE
# =============================================================================

@pytest.fixture
def temporary_user(safe_test_database):
    """
    Create a temporary user in the isolated PostgreSQL database.

    The safe_test_database fixture runs first and confirms that
    the application is connected to health_rag_migration_test.

    Cleanup removes the synthetic user and its associated records
    using the verified test database owner.
    """
    # STEP 1: Create a unique synthetic account.
    user = create_user(
        email=f"phase43-logout-{uuid4().hex}@example.com",
        password_hash="integration-test-placeholder",
    )

    user_id = user["user_id"]

    try:
        # STEP 2: Provide the temporary user to the test.
        yield user_id

    finally:
        # STEP 3: Connect directly to the isolated test database.
        # The application role intentionally lacks DELETE permission.
        with psycopg.connect(
            dbname=TEST_DATABASE,
            user=TEST_DATABASE_OWNER,
        ) as connection:

            # STEP 4: Verify the cleanup connection destination.
            actual_database = connection.execute(
                "SELECT current_database()"
            ).fetchone()[0]

            if actual_database != TEST_DATABASE:
                raise RuntimeError(
                    "Unsafe integration test cleanup destination."
                )

            # STEP 5: Remove only the temporary user.
            # This follows the established refresh integration
            # test cleanup convention.
            connection.execute(
                """
                DELETE FROM public.users
                WHERE user_id = %s
                """,
                (user_id,),
            )


# =============================================================================
# TEST 1 - VALID LOGOUT REVOKES THE DATABASE SESSION
# =============================================================================

def test_valid_logout_revokes_postgresql_session(temporary_user):
    """
    A valid current refresh token must revoke its PostgreSQL session.

    Verify the persisted revoked_at timestamp, not just the
    logout service's return value.
    """
    session_id, refresh_token = create_test_refresh_session(
        str(temporary_user)
    )

    # Confirm the session is active before logout.
    assert is_session_active(
        session_id=session_id,
        user_id=str(temporary_user),
    ) is True

    # Execute logout against the real PostgreSQL session.
    result = logout_session(refresh_token)

    assert result is True

    # Read the stored session again to verify the database update.
    stored_session = get_session(session_id)

    assert stored_session is not None
    assert stored_session["revoked_at"] is not None

    # The active-session lookup must now reject this session.
    assert is_session_active(
        session_id=session_id,
        user_id=str(temporary_user),
    ) is False


# =============================================================================
# TEST 2 - REFRESH AFTER LOGOUT IS REJECTED
# =============================================================================

def test_refresh_token_cannot_be_used_after_logout(temporary_user):
    """
    A refresh token must not issue new credentials after logout.

    This exercises both the logout service and the existing
    refresh-session service against real PostgreSQL state.
    """
    session_id, refresh_token = create_test_refresh_session(
        str(temporary_user)
    )

    # STEP 1: Revoke the session using the valid current token.
    assert logout_session(refresh_token) is True

    # STEP 2: Attempt to reuse the same token for refresh.
    refreshed_credentials = refresh_session(refresh_token)

    # A revoked session must never receive new credentials.
    assert refreshed_credentials is None

    # STEP 3: Verify the session remains revoked in PostgreSQL.
    assert get_session(session_id)["revoked_at"] is not None


# =============================================================================
# TEST 3 - INCORRECT SECRET CANNOT REVOKE SESSION
# =============================================================================

def test_incorrect_refresh_secret_cannot_revoke_session(temporary_user):
    """
    A token containing the correct session UUID but the wrong
    refresh secret must not revoke the legitimate session.
    """
    session_id, valid_token = create_test_refresh_session(
        str(temporary_user)
    )

    # Construct another syntactically valid token for the same
    # session, but with a different cryptographic secret.
    incorrect_token = build_refresh_token(
        session_id=session_id,
        secret=generate_refresh_secret(),
    )

    assert incorrect_token != valid_token

    # The database hash comparison must reject this token.
    assert logout_session(incorrect_token) is False

    # The legitimate session must remain active.
    assert get_session(session_id)["revoked_at"] is None

    assert is_session_active(
        session_id=session_id,
        user_id=str(temporary_user),
    ) is True

    # Confirm the legitimate token can still revoke the session.
    assert logout_session(valid_token) is True


# =============================================================================
# TEST 4 - REPEATED LOGOUT IS SAFE
# =============================================================================

def test_repeated_logout_does_not_revoke_twice(temporary_user):
    """
    A second logout using the same token must return False.

    The already-revoked session must remain revoked.
    """
    session_id, refresh_token = create_test_refresh_session(
        str(temporary_user)
    )

    # First logout revokes the active session.
    assert logout_session(refresh_token) is True

    first_revocation = get_session(session_id)["revoked_at"]

    assert first_revocation is not None

    # Second logout must not perform another revocation.
    assert logout_session(refresh_token) is False

    second_revocation = get_session(session_id)["revoked_at"]

    # The original revocation timestamp must remain unchanged.
    assert second_revocation == first_revocation


# =============================================================================
# TEST 5 - EXPIRED SESSION CANNOT BE LOGGED OUT
# =============================================================================

def test_expired_session_is_rejected_by_logout(temporary_user):
    """
    An expired session must not be treated as an active logout.

    Expiration is simulated only inside the isolated test database.
    """
    session_id, refresh_token = create_test_refresh_session(
        str(temporary_user)
    )

    # STEP 1: Expire the session in PostgreSQL.
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE public.user_sessions
                SET expires_at = CURRENT_TIMESTAMP
                WHERE session_id = %s
                """,
                (session_id,),
            )

    # STEP 2: Verify logout rejects the expired session.
    assert logout_session(refresh_token) is False

    # STEP 3: Confirm no revocation timestamp was written.
    stored_session = get_session(session_id)

    assert stored_session["revoked_at"] is None

    # An expired session must also fail active-session verification.
    assert is_session_active(
        session_id=session_id,
        user_id=str(temporary_user),
    ) is False


# =============================================================================
# TEST 6 - LOGOUT DOES NOT REVOKE ANOTHER SESSION
# =============================================================================

def test_logout_revokes_only_the_selected_session(temporary_user):
    """
    Logging out one session must not revoke another session
    belonging to the same user.

    This verifies per-session logout rather than global logout.
    """
    # Create two independent login sessions for the same user.
    first_session_id, first_token = create_test_refresh_session(
        str(temporary_user)
    )

    second_session_id, _ = create_test_refresh_session(
        str(temporary_user)
    )

    # Both sessions must initially be active.
    assert is_session_active(
        session_id=first_session_id,
        user_id=str(temporary_user),
    ) is True

    assert is_session_active(
        session_id=second_session_id,
        user_id=str(temporary_user),
    ) is True

    # Revoke only the first session.
    assert logout_session(first_token) is True

    # First session is revoked.
    assert get_session(first_session_id)["revoked_at"] is not None

    # Second session remains active and unchanged.
    assert get_session(second_session_id)["revoked_at"] is None

    assert is_session_active(
        session_id=second_session_id,
        user_id=str(temporary_user),
    ) is True
