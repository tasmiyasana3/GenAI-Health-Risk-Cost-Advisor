
"""Create and verify short-lived JWT access tokens.

Phase 4.3A responsibilities:
- Sign access tokens using a secret stored outside source control.
- Identify both the authenticated user and login session.
- Enforce token expiration, issuer, algorithm and token type.
- Reject malformed, expired and incorrectly signed tokens.

Database-backed session verification will be added in Phase 4.3B
and connected to protected endpoints in Phase 4.4.
"""

import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from dotenv import load_dotenv
from jwt.exceptions import InvalidTokenError


load_dotenv()

JWT_ISSUER = "insurance-cost-policy-rag"
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TYPE = "access"

DEFAULT_EXPIRY_MINUTES = 15


class TokenConfigurationError(RuntimeError):
    """Raised when JWT configuration is missing or unsafe."""


class TokenValidationError(ValueError):
    """Raised when an access token cannot be trusted."""


def normalize_uuid(value: str) -> str:
    """Validate and normalize a UUID to its canonical string form."""
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("A valid UUID is required.") from error


def get_jwt_secret() -> str:
    """Read and validate the JWT signing secret at runtime."""
    secret = os.getenv("JWT_SECRET_KEY", "")

    if (
        len(secret.encode("utf-8")) < 32
        or secret == "PASTE_YOUR_GENERATED_SECRET_HERE"
        or secret == "YOUR_EXISTING_GENERATED_SECRET"
    ):
        raise TokenConfigurationError(
            "JWT_SECRET_KEY must contain at least 32 bytes "
            "of securely generated secret material."
        )

    return secret


def get_access_token_expiry_minutes() -> int:
    """Read and validate the configured access-token lifetime."""
    raw_value = os.getenv(
        "JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
        str(DEFAULT_EXPIRY_MINUTES),
    )

    try:
        minutes = int(raw_value)
    except (TypeError, ValueError) as error:
        raise TokenConfigurationError(
            "JWT_ACCESS_TOKEN_EXPIRE_MINUTES must be an integer."
        ) from error

    if not 1 <= minutes <= 1440:
        raise TokenConfigurationError(
            "JWT access-token lifetime must be 1 to 1440 minutes."
        )

    return minutes


def create_access_token(
    user_id: str,
    session_id: str,
) -> tuple[str, int]:
    """Create a signed JWT for a user and a specific login session.

    Args:
        user_id: UUID of the registered user.
        session_id: UUID of the login session.

    Returns:
        Tuple containing the signed JWT and lifetime in seconds.
    """
    normalized_user_id = normalize_uuid(user_id)
    normalized_session_id = normalize_uuid(session_id)

    secret = get_jwt_secret()
    expiry_minutes = get_access_token_expiry_minutes()

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=expiry_minutes)

    claims = {
        "sub": normalized_user_id,
        "sid": normalized_session_id,
        "iat": now,
        "exp": expires_at,
        "iss": JWT_ISSUER,
        "token_type": ACCESS_TOKEN_TYPE,
    }

    token = jwt.encode(
        claims,
        secret,
        algorithm=JWT_ALGORITHM,
    )

    return token, expiry_minutes * 60


def verify_access_token(token: str) -> dict[str, str]:
    """Validate a JWT and return its user and session identifiers.

    This checks token integrity and claims only.

    IMPORTANT:
        A cryptographically valid JWT is not necessarily an active
        session. Database-backed session revocation checks must also
        be performed before granting access to protected resources.
    """
    if not isinstance(token, str) or not token:
        raise TokenValidationError("Invalid access token.")

    secret = get_jwt_secret()

    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
            options={
                "require": [
                    "sub",
                    "sid",
                    "iat",
                    "exp",
                    "iss",
                    "token_type",
                ],
            },
        )

        if claims.get("token_type") != ACCESS_TOKEN_TYPE:
            raise TokenValidationError("Invalid token type.")

        subject = claims.get("sub")
        session_id = claims.get("sid")

        if not isinstance(subject, str):
            raise TokenValidationError("Invalid user identity.")

        if not isinstance(session_id, str):
            raise TokenValidationError("Invalid session identity.")

        return {
            "user_id": normalize_uuid(subject),
            "session_id": normalize_uuid(session_id),
        }

    except (InvalidTokenError, ValueError, TypeError) as error:
        raise TokenValidationError(
            "Invalid or expired access token."
        ) from error
