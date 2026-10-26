
"""
MODULE NAME
-----------
SESSION DATABASE SERVICE

PURPOSE
-------
Manage PostgreSQL-backed authentication sessions, including creation,
lookup, active-session verification, refresh-token rotation, replay
detection, and revocation.

ENVIRONMENT / CONFIGURATION
---------------------------
Uses the existing PostgreSQL connection configuration provided by
services.database_service.

DEPENDENCIES
------------
Python standard library: datetime, enum, hmac, uuid.
Project service: services.database_service.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Validate session IDs, token hashes, and expiration timestamps.
2. Create and retrieve authentication sessions.
3. Verify session ownership and active status.
4. Preserve the existing boolean rotation API.
5. Atomically rotate refresh-token hashes.
6. Detect reuse of previously consumed refresh tokens.
7. Revoke sessions after confirmed replay.
8. Preserve transactional rollback on database errors.

SECURITY NOTES
--------------
Only refresh-secret hashes are stored in PostgreSQL.
Never log plaintext refresh tokens.
SELECT FOR UPDATE serializes rotation attempts per session.
Consumed-token replay revokes the affected session.
"""

import hmac

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from services.database_service import get_db_connection


# =============================================================================
# INPUT VALIDATION
# =============================================================================

def _validate_uuid(value: str) -> UUID:
    """Validate and normalize a session or user UUID."""
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("Invalid UUID.") from error


def _validate_token_hash(token_hash: str) -> str:
    """Require a lowercase, 64-character SHA-256 hexadecimal digest."""
    if (
        not isinstance(token_hash, str)
        or len(token_hash) != 64
        or any(character not in "0123456789abcdef" for character in token_hash)
    ):
        raise ValueError(
            "Refresh-token hash must be a 64-character "
            "lowercase SHA-256 digest."
        )

    return token_hash


def _validate_expiry(expires_at: datetime) -> datetime:
    """Require a timezone-aware future expiration timestamp."""
    if (
        not isinstance(expires_at, datetime)
        or expires_at.tzinfo is None
        or expires_at.utcoffset() is None
    ):
        raise ValueError(
            "Session expiration must be timezone-aware."
        )

    if expires_at <= datetime.now(timezone.utc):
        raise ValueError("Session expiration must be in the future.")

    return expires_at


# =============================================================================
# SESSION CREATION
# =============================================================================

def create_session(
    user_id: str,
    refresh_token_hash: str,
    expires_at: datetime,
    session_id: str | None = None,
) -> dict:
    """Create a session with a generated or caller-supplied UUID."""
    validated_user_id = _validate_uuid(user_id)
    validated_hash = _validate_token_hash(refresh_token_hash)
    validated_expiry = _validate_expiry(expires_at)

    validated_session_id = (
        _validate_uuid(session_id)
        if session_id is not None
        else uuid4()
    )

    query = """
        INSERT INTO public.user_sessions (
            session_id,
            user_id,
            refresh_token_hash,
            expires_at
        )
        VALUES (%s, %s, %s, %s)
        RETURNING
            session_id,
            user_id,
            created_at,
            rotated_at,
            expires_at,
            revoked_at
    """

    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                query,
                (
                    validated_session_id,
                    validated_user_id,
                    validated_hash,
                    validated_expiry,
                ),
            )

            return cursor.fetchone()


# =============================================================================
# SESSION RETRIEVAL
# =============================================================================

def get_session(session_id: str) -> dict | None:
    """Retrieve session metadata without returning refresh-token hashes."""
    validated_id = _validate_uuid(session_id)

    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    session_id,
                    user_id,
                    created_at,
                    rotated_at,
                    expires_at,
                    revoked_at
                FROM public.user_sessions
                WHERE session_id = %s
                """,
                (validated_id,),
            )

            return cursor.fetchone()


def is_session_active(
    session_id: str,
    user_id: str,
) -> bool:
    """Verify that a session belongs to the user and remains active."""
    validated_session_id = _validate_uuid(session_id)
    validated_user_id = _validate_uuid(user_id)

    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM public.user_sessions
                    WHERE session_id = %s
                      AND user_id = %s
                      AND revoked_at IS NULL
                      AND expires_at > CURRENT_TIMESTAMP
                ) AS active
                """,
                (
                    validated_session_id,
                    validated_user_id,
                ),
            )

            return bool(cursor.fetchone()["active"])


# =============================================================================
# EXISTING ROTATION API - PRESERVED FOR BACKWARD COMPATIBILITY
# =============================================================================

def rotate_session_token(
    session_id: str,
    expected_token_hash: str,
    new_token_hash: str,
    new_expires_at: datetime,
) -> bool:
    """Atomically rotate the current refresh hash.

    This is the existing Phase 4.3B API.

    Returns True after successful rotation and False for a missing,
    revoked, expired, or mismatched session.

    A mismatched token does not revoke the session in this legacy
    interface. The replay-aware interface below handles that policy.
    """
    validated_id = _validate_uuid(session_id)
    expected_hash = _validate_token_hash(expected_token_hash)
    replacement_hash = _validate_token_hash(new_token_hash)
    validated_expiry = _validate_expiry(new_expires_at)

    if hmac.compare_digest(expected_hash, replacement_hash):
        raise ValueError(
            "The replacement token hash must be different."
        )

    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    refresh_token_hash,
                    expires_at,
                    revoked_at
                FROM public.user_sessions
                WHERE session_id = %s
                FOR UPDATE
                """,
                (validated_id,),
            )

            session = cursor.fetchone()

            if session is None:
                return False

            if session["revoked_at"] is not None:
                return False

            if session["expires_at"] <= datetime.now(timezone.utc):
                return False

            current_hash = session["refresh_token_hash"].strip()

            if not hmac.compare_digest(current_hash, expected_hash):
                return False

            cursor.execute(
                """
                INSERT INTO public.refresh_token_history (
                    token_hash,
                    session_id
                )
                VALUES (%s, %s)
                """,
                (expected_hash, validated_id),
            )

            cursor.execute(
                """
                UPDATE public.user_sessions
                SET
                    refresh_token_hash = %s,
                    rotated_at = CURRENT_TIMESTAMP,
                    expires_at = %s
                WHERE session_id = %s
                """,
                (
                    replacement_hash,
                    validated_expiry,
                    validated_id,
                ),
            )

            return True


# =============================================================================
# PHASE 4.3D - REPLAY-AWARE ROTATION
# =============================================================================

class RefreshRotationStatus(str, Enum):
    """Possible outcomes of replay-aware refresh-token rotation."""

    ROTATED = "rotated"
    REPLAYED = "replayed"
    INVALID = "invalid"


def rotate_session_token_checked(
    session_id: str,
    expected_token_hash: str,
    new_token_hash: str,
    new_expires_at: datetime,
) -> tuple[RefreshRotationStatus, str | None]:
    """Atomically verify and rotate a refresh token.

    Returns
    -------
    tuple[RefreshRotationStatus, str | None]
        ROTATED with the verified user ID on success.
        REPLAYED when a consumed token is reused.
        INVALID for all other rejected tokens or sessions.

    Concurrency
    -----------
    The session row is locked before checking the active hash or
    consumed-token history. Two requests using the same refresh
    token cannot both succeed.

    Security
    --------
    A confirmed replay revokes the session. An unrelated incorrect
    token does not revoke the session.
    """
    validated_id = _validate_uuid(session_id)
    expected_hash = _validate_token_hash(expected_token_hash)
    replacement_hash = _validate_token_hash(new_token_hash)
    validated_expiry = _validate_expiry(new_expires_at)

    if hmac.compare_digest(expected_hash, replacement_hash):
        raise ValueError(
            "The replacement token hash must be different."
        )

    with get_db_connection() as connection:
        with connection.cursor() as cursor:

            # Lock this session until the transaction finishes.
            cursor.execute(
                """
                SELECT
                    user_id,
                    refresh_token_hash,
                    expires_at,
                    revoked_at
                FROM public.user_sessions
                WHERE session_id = %s
                FOR UPDATE
                """,
                (validated_id,),
            )

            session = cursor.fetchone()

            if session is None:
                return RefreshRotationStatus.INVALID, None

            if session["revoked_at"] is not None:
                return RefreshRotationStatus.INVALID, None

            if session["expires_at"] <= datetime.now(timezone.utc):
                return RefreshRotationStatus.INVALID, None

            current_hash = session["refresh_token_hash"].strip()

            # Check whether the supplied token is the current one.
            if not hmac.compare_digest(current_hash, expected_hash):

                # A mismatch alone is not proof of replay.
                # Only a previously consumed token is classified
                # as replayed.
                cursor.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM public.refresh_token_history
                        WHERE session_id = %s
                          AND token_hash = %s
                    ) AS consumed
                    """,
                    (validated_id, expected_hash),
                )

                was_consumed = bool(cursor.fetchone()["consumed"])

                if was_consumed:
                    cursor.execute(
                        """
                        UPDATE public.user_sessions
                        SET revoked_at = CURRENT_TIMESTAMP
                        WHERE session_id = %s
                          AND revoked_at IS NULL
                        """,
                        (validated_id,),
                    )

                    return RefreshRotationStatus.REPLAYED, None

                return RefreshRotationStatus.INVALID, None

            # The current token is valid.
            # Record it as consumed before replacing its hash.
            cursor.execute(
                """
                INSERT INTO public.refresh_token_history (
                    token_hash,
                    session_id
                )
                VALUES (%s, %s)
                """,
                (expected_hash, validated_id),
            )

            cursor.execute(
                """
                UPDATE public.user_sessions
                SET
                    refresh_token_hash = %s,
                    rotated_at = CURRENT_TIMESTAMP,
                    expires_at = %s
                WHERE session_id = %s
                """,
                (
                    replacement_hash,
                    validated_expiry,
                    validated_id,
                ),
            )

            return (
                RefreshRotationStatus.ROTATED,
                str(session["user_id"]),
            )


# =============================================================================
# SESSION REVOCATION
# =============================================================================

def revoke_session(session_id: str) -> bool:
    """Revoke a session and prevent future authenticated access."""
    validated_id = _validate_uuid(session_id)

    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE public.user_sessions
                SET revoked_at = CURRENT_TIMESTAMP
                WHERE session_id = %s
                  AND revoked_at IS NULL
                RETURNING session_id
                """,
                (validated_id,),
            )

            return cursor.fetchone() is not None
