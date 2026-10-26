
"""
PHASE 4.3C LOGIN DATABASE INTEGRATION TESTS

PURPOSE
-------
Verify secure login and persistent authentication sessions against
an isolated PostgreSQL test database.

ENVIRONMENT / CONFIGURATION
---------------------------
Requires RUN_PHASE4_DB_TESTS=1.

The shared safe_test_database fixture selects and verifies the
isolated database before test data is created.

DEPENDENCIES
------------
pytest, psycopg, existing authentication services, and the shared
database safety configuration in tests/conftest.py.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Successful credential authentication.
2. JWT user and session identity.
3. Persistence of an active PostgreSQL session.
4. Storage of refresh-secret hashes rather than plaintext.
5. Rejection of incorrect passwords without session creation.
6. Safe cleanup of temporary users and related sessions.

SECURITY NOTES
--------------
Never execute test cleanup against the working database.
The restricted application role must not receive DELETE privileges.
Temporary users are removed through the verified test-database owner.
Do not log passwords, access tokens, or refresh tokens.
"""

from uuid import uuid4

import psycopg
import pytest

from services.auth_service import hash_password
from services.database_service import (
    create_user,
    get_db_connection,
)
from services.login_service import login_user
from services.refresh_token_service import (
    hash_refresh_secret,
    parse_refresh_token,
)
from services.session_database_service import is_session_active
from services.token_service import verify_access_token


# =============================================================================
# ISOLATED DATABASE CONFIGURATION
# =============================================================================

from conftest import (
    TEST_DATABASE_NAME,
    TEST_DATABASE_OWNER,
)


# =============================================================================
# TEMPORARY USER FIXTURE
# =============================================================================

@pytest.fixture
def login_test_user(safe_test_database):
    """
    Create a synthetic account and safely remove it after testing.

    The shared safety fixture runs before user creation.

    The cleanup connection uses the verified test-database owner,
    rather than the restricted application role.
    """
    email = f"phase43c-{uuid4().hex}@example.com"
    password = "SyntheticPassword123!"

    user = create_user(
        email=email,
        password_hash=hash_password(password),
    )

    user_id = str(user["user_id"])

    try:
        yield {
            "user_id": user_id,
            "email": email,
            "password": password,
        }

    finally:
        # Open an independent cleanup connection as the test owner.
        with psycopg.connect(
            dbname=TEST_DATABASE_NAME,
            user=TEST_DATABASE_OWNER,
        ) as connection:

            # Verify the destination immediately before deletion.
            actual_database = connection.execute(
                "SELECT current_database()"
            ).fetchone()[0]

            if actual_database != TEST_DATABASE_NAME:
                raise RuntimeError(
                    "Unsafe database connection during test cleanup."
                )

            # Related sessions and refresh history are removed
            # through the existing ON DELETE CASCADE constraints.
            connection.execute(
                """
                DELETE FROM public.users
                WHERE user_id = %s
                """,
                (user_id,),
            )


# =============================================================================
# TEST 1: SUCCESSFUL LOGIN AND PERSISTENCE
# =============================================================================

def test_login_creates_persistent_session(
    login_test_user,
    monkeypatch,
):
    """
    Verify real authentication and PostgreSQL session persistence.

    The refresh secret must never appear in the stored hash field.
    """
    monkeypatch.setenv(
        "JWT_SECRET_KEY",
        "integration-test-secret-" * 3,
    )
    monkeypatch.setenv(
        "JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
        "15",
    )
    monkeypatch.setenv(
        "REFRESH_TOKEN_EXPIRE_DAYS",
        "7",
    )

    user_id = login_test_user["user_id"]

    result = login_user(
        login_test_user["email"],
        login_test_user["password"],
    )

    assert result is not None
    assert result.access_token
    assert result.refresh_token
    assert result.expires_in == 900

    # Verify the JWT identifies the correct user and session.
    claims = verify_access_token(result.access_token)

    # The existing token verifier may normalize JWT claims into
    # user_id/session_id, or preserve the original sub/sid names.
    token_user_id = claims.get("user_id", claims.get("sub"))
    token_session_id = claims.get(
        "session_id",
        claims.get("sid"),
    )

    assert token_user_id == user_id
    assert token_session_id == result.session_id

    # The persisted session must be active for the correct user.
    assert is_session_active(
        session_id=result.session_id,
        user_id=user_id,
    ) is True

    # The refresh token contains the session ID and random secret.
    session_id, secret = parse_refresh_token(
        result.refresh_token
    )

    assert session_id == result.session_id

    # Read the stored hash using the restricted application role.
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    user_id,
                    refresh_token_hash,
                    revoked_at
                FROM public.user_sessions
                WHERE session_id = %s
                """,
                (result.session_id,),
            )

            stored = cursor.fetchone()

    assert stored is not None
    assert str(stored["user_id"]) == user_id
    assert stored["revoked_at"] is None

    stored_hash = stored["refresh_token_hash"].strip()

    assert stored_hash == hash_refresh_secret(secret)
    assert len(stored_hash) == 64
    assert secret != stored_hash
    assert result.refresh_token != stored_hash


# =============================================================================
# TEST 2: INVALID PASSWORD
# =============================================================================

def test_invalid_password_does_not_create_session(
    login_test_user,
):
    """
    Incorrect credentials must not create a database session.

    Check session count before and after the login attempt.
    """
    user_id = login_test_user["user_id"]

    def count_sessions() -> int:
        """Count sessions belonging to the synthetic test user."""
        with get_db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*) AS session_count
                    FROM public.user_sessions
                    WHERE user_id = %s
                    """,
                    (user_id,),
                )

                return cursor.fetchone()["session_count"]

    before = count_sessions()

    result = login_user(
        login_test_user["email"],
        "IncorrectPassword123!",
    )

    after = count_sessions()

    assert result is None
    assert after == before
