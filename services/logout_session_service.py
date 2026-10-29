
"""
MODULE NAME
-----------
LOGOUT SESSION SERVICE

PURPOSE
-------
Revoke the authentication session associated with a valid current
refresh token.

ENVIRONMENT / CONFIGURATION
---------------------------
Uses the existing PostgreSQL configuration.

DEPENDENCIES
------------
services.database_service
services.refresh_token_service

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Reject missing and malformed refresh tokens.
2. Verify the current refresh-token hash.
3. Revoke only the authenticated session.
4. Handle expired, revoked, and unknown sessions safely.
5. Serialize logout against concurrent refresh operations.

SECURITY NOTES
--------------
Never trust a session UUID without verifying its refresh secret.
Never log plaintext tokens.
Use constant-time hash comparison.
"""

import hmac

from datetime import datetime, timezone

from services.database_service import get_db_connection
from services.refresh_token_service import (
    hash_refresh_secret,
    parse_refresh_token,
)


# =============================================================================
# SESSION LOGOUT
# =============================================================================

def logout_session(cookie_token: str | None) -> bool:
    """Revoke a session if the supplied refresh token is current.

    Returns:
        True if an active session was revoked.
        False if the token or session is invalid.

    Raises:
        Database errors are propagated to the API layer.
    """
    if not cookie_token:
        return False

    try:
        session_id, secret = parse_refresh_token(cookie_token)
    except ValueError:
        return False

    expected_hash = hash_refresh_secret(secret)

    # Lock the session row so refresh rotation and logout cannot
    # both modify the same session concurrently.
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
                (session_id,),
            )

            session = cursor.fetchone()

            if session is None:
                return False

            if session["revoked_at"] is not None:
                return False

            if session["expires_at"] <= datetime.now(timezone.utc):
                return False

            stored_hash = session["refresh_token_hash"].strip()

            if not hmac.compare_digest(
                stored_hash,
                expected_hash,
            ):
                return False

            cursor.execute(
                """
                UPDATE public.user_sessions
                SET revoked_at = CURRENT_TIMESTAMP
                WHERE session_id = %s
                  AND revoked_at IS NULL
                RETURNING session_id
                """,
                (session_id,),
            )

            return cursor.fetchone() is not None


# =============================================================================
# PHASE 4.4.6 - VERIFIED LOGOUT DOCUMENT CLEANUP
# =============================================================================
#
# PURPOSE
# -------
# Attempt immediate removal of temporary insurance PDFs after
# a successfully authenticated logout.
#
# SECURITY NOTES
# --------------
# The original logout function verifies the refresh secret before
# revoking the session.
#
# The parsed session ID is used for cleanup only when that
# verification and revocation succeeded.
#
# Cleanup failure must not undo a successful session revocation.
# The background scheduler will retry eligible documents.

import logging

from services.document_lifecycle import cleanup_logged_out_session


_logout_logger = logging.getLogger(__name__)

# Retain the existing verified logout implementation.
_original_logout_session = logout_session


def logout_session(cookie_token: str | None) -> bool:
    """
    Revoke a verified login session and attempt PDF cleanup.

    Returns
    -------
    bool
        True when the existing logout service revoked a session.
        False when the token/session was invalid.

    Security
    --------
    Never trigger cleanup for an unverified refresh token.
    """
    revoked = _original_logout_session(cookie_token)

    if not revoked:
        return False

    try:
        # The original service has already verified this token
        # and successfully revoked its corresponding session.
        verified_session_id, _ = parse_refresh_token(
            cookie_token
        )

        statistics = cleanup_logged_out_session(
            str(verified_session_id)
        )

        _logout_logger.info(
            "document_lifecycle "
            "event=logout_cleanup "
            "session_id=%s outcome=complete "
            "deleted=%d busy=%d failed=%d",
            verified_session_id,
            statistics["deleted"],
            statistics["busy"],
            statistics["failed"],
        )

    except Exception:
        # Authentication remains revoked even if ChromaDB or
        # PostgreSQL cleanup is temporarily unavailable.
        _logout_logger.exception(
            "Verified logout succeeded; "
            "document cleanup will be retried."
        )

    return True
