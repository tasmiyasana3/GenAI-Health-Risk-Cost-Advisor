
"""
MODULE NAME
-----------
REFRESH SESSION SERVICE

PURPOSE
-------
Exchange an existing opaque refresh token for a new access token
and a rotated refresh token.

ENVIRONMENT / CONFIGURATION
---------------------------
Uses the existing JWT and refresh-token configuration.

DEPENDENCIES
------------
services.refresh_token_service
services.token_service
services.session_database_service

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Reject missing or malformed refresh tokens.
2. Retrieve session ownership metadata.
3. Prepare replacement credentials before database rotation.
4. Atomically verify and rotate the stored refresh-token hash.
5. Return credentials only after successful rotation.
6. Reject consumed-token replay and invalid sessions.

SECURITY NOTES
--------------
Never log or expose plaintext refresh tokens.
The database is authoritative for token validity.
A JWT prepared before rotation is never returned on failed rotation.
"""

from dataclasses import dataclass

from services.refresh_token_service import (
    build_refresh_token,
    generate_refresh_secret,
    get_refresh_token_expiry,
    hash_refresh_secret,
    parse_refresh_token,
)

from services.session_database_service import (
    RefreshRotationStatus,
    get_session,
    rotate_session_token_checked,
)

from services.token_service import create_access_token


# =============================================================================
# RESULT MODEL
# =============================================================================

@dataclass(frozen=True)
class RefreshResult:
    """Credentials returned after successful refresh-token rotation."""

    access_token: str
    refresh_token: str
    expires_in: int


# =============================================================================
# REFRESH-TOKEN ORCHESTRATION
# =============================================================================

def refresh_session(
    cookie_token: str | None,
) -> RefreshResult | None:
    """Verify and rotate a refresh token.

    Returns None when the supplied token is missing, malformed,
    expired, revoked, unrelated, or already consumed.

    Unexpected infrastructure errors propagate to the API layer,
    which returns a generic service-unavailable response.
    """
    # -----------------------------------------------------------------
    # STEP 1: Reject absent refresh credentials.
    # -----------------------------------------------------------------

    if not cookie_token:
        return None

    # -----------------------------------------------------------------
    # STEP 2: Parse the versioned token.
    # -----------------------------------------------------------------

    try:
        session_id, old_secret = parse_refresh_token(cookie_token)
    except ValueError:
        return None

    # Parsing proves only that the token has the correct format.
    # The database must verify the secret before authentication.
    old_hash = hash_refresh_secret(old_secret)

    # -----------------------------------------------------------------
    # STEP 3: Retrieve session ownership metadata.
    # -----------------------------------------------------------------

    session = get_session(session_id)

    if session is None:
        return None

    user_id = str(session["user_id"])

    # -----------------------------------------------------------------
    # STEP 4: Prepare replacement refresh credentials.
    # -----------------------------------------------------------------

    new_secret = generate_refresh_secret()
    new_hash = hash_refresh_secret(new_secret)

    new_refresh_token = build_refresh_token(
        session_id=session_id,
        secret=new_secret,
    )

    new_expiry = get_refresh_token_expiry()

    # -----------------------------------------------------------------
    # STEP 5: Prepare the access token before modifying PostgreSQL.
    # -----------------------------------------------------------------

    # If JWT configuration or signing fails, the existing refresh
    # token remains valid because rotation has not happened yet.
    access_token, expires_in = create_access_token(
        user_id=user_id,
        session_id=session_id,
    )

    # -----------------------------------------------------------------
    # STEP 6: Verify the current token and rotate atomically.
    # -----------------------------------------------------------------

    status, verified_user_id = rotate_session_token_checked(
        session_id=session_id,
        expected_token_hash=old_hash,
        new_token_hash=new_hash,
        new_expires_at=new_expiry,
    )

    if status != RefreshRotationStatus.ROTATED:
        return None

    # The database row is authoritative. The user ID must match
    # the metadata used when preparing the access token.
    if verified_user_id != user_id:
        raise RuntimeError(
            "Session ownership mismatch during refresh."
        )

    # -----------------------------------------------------------------
    # STEP 7: Return credentials only after successful rotation.
    # -----------------------------------------------------------------

    return RefreshResult(
        access_token=access_token,
        refresh_token=new_refresh_token,
        expires_in=expires_in,
    )
