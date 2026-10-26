
"""PostgreSQL persistence for authentication sessions.

Responsibilities:
- Create and retrieve sessions.
- Verify active session status.
- Atomically rotate refresh-token hashes.
- Record consumed refresh-token hashes.
- Revoke sessions during logout.

Security:
- Store only refresh-token hashes.
- Use row-level locking during rotation.
- Commit token rotation and history together.
- Never log plaintext refresh tokens.

This module does not generate tokens or set HTTP cookies.
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from services.database_service import get_db_connection


def _validate_uuid(value: str) -> UUID:
    """Validate and normalize a UUID."""
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("Invalid UUID.") from error


def _validate_token_hash(token_hash: str) -> str:
    """Validate a lowercase SHA-256 hexadecimal digest."""
    if (
        not isinstance(token_hash, str)
        or len(token_hash) != 64
        or any(c not in "0123456789abcdef" for c in token_hash)
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


def create_session(
    user_id: str,
    refresh_token_hash: str,
    expires_at: datetime,
) -> dict:
    """Create a session for an existing user."""
    validated_user_id = _validate_uuid(user_id)
    validated_hash = _validate_token_hash(refresh_token_hash)
    validated_expiry = _validate_expiry(expires_at)

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
                    uuid4(),
                    validated_user_id,
                    validated_hash,
                    validated_expiry,
                ),
            )
            return cursor.fetchone()


def get_session(session_id: str) -> dict | None:
    """Retrieve session metadata without returning token hashes."""
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
    """Check ownership, expiration and revocation."""
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


def rotate_session_token(
    session_id: str,
    expected_token_hash: str,
    new_token_hash: str,
    new_expires_at: datetime,
) -> bool:
    """Atomically rotate a refresh token and record its history.

    Returns True only when the current hash matches and the
    session is active.

    Returns False for an expired, revoked, missing or mismatched
    session. Token-replay classification is handled separately.

    The transaction guarantees that token history and the
    current session hash cannot be updated independently.
    """
    validated_id = _validate_uuid(session_id)
    expected_hash = _validate_token_hash(expected_token_hash)
    replacement_hash = _validate_token_hash(new_token_hash)
    validated_expiry = _validate_expiry(new_expires_at)

    if expected_hash == replacement_hash:
        raise ValueError(
            "The replacement token hash must be different."
        )

    with get_db_connection() as connection:
        with connection.cursor() as cursor:

            # Lock the session row until this transaction finishes.
            # Concurrent refresh attempts for the same session
            # must wait for this operation to commit or roll back.
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

            if session["refresh_token_hash"].strip() != expected_hash:
                return False

            # Record the consumed token before replacing it.
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

            # Replace the current token hash.
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
