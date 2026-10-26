
"""
REFRESH TOKEN SERVICE

PURPOSE
-------
Generate, construct, parse, and hash opaque refresh tokens used for
persistent authentication sessions.

Each refresh token contains:
    - A format version
    - The PostgreSQL session UUID
    - A cryptographically secure random secret

Only the SHA-256 hash of the random secret is stored in PostgreSQL.
The plaintext refresh token is delivered to the browser as an
HttpOnly cookie.

ENVIRONMENT / CONFIGURATION
---------------------------
Optional environment variable:

    REFRESH_TOKEN_EXPIRE_DAYS=7

The default refresh-token lifetime is seven days.
Allowed values are between 1 and 30 days.

No machine-specific paths or credentials are hardcoded.

DEPENDENCIES
------------
Python standard library:
    - base64
    - binascii
    - hashlib
    - os
    - secrets
    - datetime
    - uuid

Existing project services:
    - login_service.py generates and issues refresh tokens.
    - session_database_service.py stores refresh-secret hashes.
    - Phase 4.3D will use token parsing during refresh rotation.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Validate refresh-token lifetime configuration.
2. Generate cryptographically unpredictable secrets.
3. Calculate SHA-256 hashes of refresh secrets.
4. Construct versioned refresh tokens.
5. Parse and validate refresh tokens.
6. Reject malformed, truncated, or incorrectly encoded secrets.

SECURITY NOTES
--------------
- Generate secrets using Python's cryptographic secrets module.
- Never store plaintext refresh secrets in PostgreSQL.
- Never log refresh tokens or their plaintext secrets.
- Use canonical URL-safe Base64 encoding.
- Validate token structure before database operations.
- Parsing does not prove that a token is authenticated.
  Database verification is required before accepting it.
"""

import base64
import binascii
import hashlib
import os
import secrets

from datetime import datetime, timedelta, timezone
from uuid import UUID


# =============================================================================
# REFRESH TOKEN CONFIGURATION
# =============================================================================

DEFAULT_REFRESH_TOKEN_DAYS = 7
MAX_REFRESH_TOKEN_DAYS = 30

REFRESH_TOKEN_SECRET_BYTES = 32
REFRESH_TOKEN_VERSION = "v1"


def get_refresh_token_lifetime_days() -> int:
    """
    Read and validate the refresh-token lifetime.

    Returns
    -------
    int
        Configured lifetime in days.

    Raises
    ------
    ValueError
        If the configured value is not an integer between 1 and 30.
    """
    raw_value = os.getenv(
        "REFRESH_TOKEN_EXPIRE_DAYS",
        str(DEFAULT_REFRESH_TOKEN_DAYS),
    )

    try:
        days = int(raw_value)

    except (TypeError, ValueError) as error:
        raise ValueError(
            "REFRESH_TOKEN_EXPIRE_DAYS must be an integer."
        ) from error

    if not 1 <= days <= MAX_REFRESH_TOKEN_DAYS:
        raise ValueError(
            "Refresh-token lifetime must be between 1 and 30 days."
        )

    return days


def get_refresh_token_expiry() -> datetime:
    """
    Calculate a timezone-aware refresh-token expiration timestamp.

    Returns
    -------
    datetime
        Future expiration timestamp in UTC.
    """
    lifetime_days = get_refresh_token_lifetime_days()

    return datetime.now(timezone.utc) + timedelta(
        days=lifetime_days
    )


# =============================================================================
# CRYPTOGRAPHIC SECRET GENERATION
# =============================================================================

def generate_refresh_secret() -> str:
    """
    Generate a cryptographically secure random refresh secret.

    Uses 32 random bytes (256 bits of entropy) encoded as a
    URL-safe Base64 string.
    """
    return secrets.token_urlsafe(
        REFRESH_TOKEN_SECRET_BYTES
    )


def hash_refresh_secret(secret: str) -> str:
    """
    Calculate the SHA-256 hash of a refresh secret.

    The resulting lowercase hexadecimal digest is compatible
    with the existing PostgreSQL CHAR(64) refresh-token column.

    Parameters
    ----------
    secret : str
        Plaintext refresh secret.

    Returns
    -------
    str
        64-character lowercase hexadecimal digest.
    """
    if not isinstance(secret, str) or not secret:
        raise ValueError("A refresh secret is required.")

    return hashlib.sha256(
        secret.encode("utf-8")
    ).hexdigest()


# =============================================================================
# REFRESH TOKEN CONSTRUCTION
# =============================================================================

def build_refresh_token(
    session_id: str,
    secret: str,
) -> str:
    """
    Construct a versioned opaque refresh token.

    Token format
    ------------
    v1.<session_uuid>.<random_secret>

    The session UUID identifies the PostgreSQL session.
    The random secret proves possession of the refresh token.
    """
    try:
        normalized_session_id = str(
            UUID(str(session_id))
        )

    except (TypeError, ValueError, AttributeError) as error:
        raise ValueError(
            "Invalid session ID."
        ) from error

    if not isinstance(secret, str) or not secret:
        raise ValueError(
            "A refresh secret is required."
        )

    # Validate the secret before constructing the token.
    decoded_secret = secrets_token_bytes(secret)

    if len(decoded_secret) != REFRESH_TOKEN_SECRET_BYTES:
        raise ValueError(
            "Invalid refresh secret length."
        )

    return (
        f"{REFRESH_TOKEN_VERSION}."
        f"{normalized_session_id}."
        f"{secret}"
    )


# =============================================================================
# REFRESH TOKEN PARSING
# =============================================================================

def parse_refresh_token(
    token: str,
) -> tuple[str, str]:
    """
    Parse and validate a versioned refresh token.

    Parameters
    ----------
    token : str
        Refresh token received from the browser.

    Returns
    -------
    tuple[str, str]
        Normalized session UUID and plaintext refresh secret.

    Raises
    ------
    ValueError
        If the token is malformed or incorrectly encoded.

    Important
    ---------
    Parsing validates the token format only.
    It does not verify the token against PostgreSQL.
    """
    if (
        not isinstance(token, str)
        or not token
        or len(token) > 256
    ):
        raise ValueError(
            "Invalid refresh token."
        )

    parts = token.split(".")

    if (
        len(parts) != 3
        or parts[0] != REFRESH_TOKEN_VERSION
    ):
        raise ValueError(
            "Invalid refresh token."
        )

    _, session_id, secret = parts

    try:
        normalized_session_id = str(
            UUID(session_id)
        )

    except (TypeError, ValueError, AttributeError) as error:
        raise ValueError(
            "Invalid refresh token."
        ) from error

    # A 32-byte secret encoded with URL-safe Base64 has
    # exactly 43 characters when padding is removed.
    if len(secret) != 43:
        raise ValueError(
            "Invalid refresh token."
        )

    decoded_secret = secrets_token_bytes(secret)

    if len(decoded_secret) != REFRESH_TOKEN_SECRET_BYTES:
        raise ValueError(
            "Invalid refresh token."
        )

    return normalized_session_id, secret


# =============================================================================
# URL-SAFE BASE64 VALIDATION
# =============================================================================

def secrets_token_bytes(secret: str) -> bytes:
    """
    Decode and validate a URL-safe Base64 refresh secret.

    The function verifies that the decoded bytes produce exactly
    the same canonical, unpadded Base64 representation.

    This prevents alternative encodings of the same secret
    from being accepted as different token strings.
    """
    if not isinstance(secret, str) or not secret:
        raise ValueError(
            "Invalid refresh secret."
        )

    try:
        decoded = base64.b64decode(
            secret + "=" * (-len(secret) % 4),
            altchars=b"-_",
            validate=True,
        )

    except (ValueError, binascii.Error) as error:
        raise ValueError(
            "Invalid refresh secret."
        ) from error

    # Re-encode to ensure the supplied string uses the
    # canonical URL-safe Base64 representation.
    canonical_secret = (
        base64.urlsafe_b64encode(decoded)
        .rstrip(b"=")
        .decode("ascii")
    )

    if canonical_secret != secret:
        raise ValueError(
            "Noncanonical refresh secret."
        )

    return decoded
