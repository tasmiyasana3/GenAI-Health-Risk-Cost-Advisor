
"""Secure password-login orchestration.

PURPOSE
-------
Issue a JWT and opaque refresh token for a committed PostgreSQL session.

ENVIRONMENT / CONFIGURATION
---------------------------
JWT_SECRET_KEY, JWT_ACCESS_TOKEN_EXPIRE_MINUTES and REFRESH_TOKEN_EXPIRE_DAYS.
HTTP cookie configuration is validated separately by the API route.

DEPENDENCIES
------------
auth_service, token_service, refresh_token_service, session_database_service.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
Reject invalid credentials; validate configuration; prepare both tokens before
creating a session; commit session before returning tokens; fail closed.

SECURITY NOTES
--------------
Never log passwords, JWTs or refresh secrets. A committed session may remain
if HTTP delivery fails after commit; expiry and retention handle that case.
"""

from dataclasses import dataclass
from uuid import uuid4

from services.auth_service import authenticate_user
from services.refresh_token_service import (
    build_refresh_token,
    generate_refresh_secret,
    get_refresh_token_expiry,
    hash_refresh_secret,
)
from services.session_database_service import create_session
from services.token_service import (
    create_access_token,
    get_access_token_expiry_minutes,
    get_jwt_secret,
)


@dataclass(frozen=True)
class LoginResult:
    """Return only after the matching database session commits."""

    access_token: str
    refresh_token: str
    expires_in: int
    session_id: str


def login_user(email: str, password: str) -> LoginResult | None:
    """Authenticate and issue tokens, persisting the session as the final step.

    Raises configuration, signing, and database exceptions to the API layer.
    No session is inserted if either token cannot be constructed.
    """
    if not isinstance(email, str) or not isinstance(password, str):
        return None

    normalized_email = email.strip().lower()
    user_id = authenticate_user(email=normalized_email, password=password)
    if user_id is None:
        return None

    # Validate configuration and token lifetime before any session write.
    get_jwt_secret()
    get_access_token_expiry_minutes()
    refresh_expiry = get_refresh_token_expiry()

    # Generate the stable session identifier before constructing either token.
    session_id = str(uuid4())
    refresh_secret = generate_refresh_secret()
    refresh_hash = hash_refresh_secret(refresh_secret)

    # Token generation failures leave PostgreSQL unchanged.
    access_token, expires_in = create_access_token(
        user_id=user_id,
        session_id=session_id,
    )
    refresh_token = build_refresh_token(
        session_id=session_id,
        secret=refresh_secret,
    )

    # The database connection context commits or rolls back this insert.
    # If insertion or commit fails, this function returns no tokens.
    create_session(
        user_id=user_id,
        refresh_token_hash=refresh_hash,
        expires_at=refresh_expiry,
        session_id=session_id,
    )

    return LoginResult(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        session_id=session_id,
    )
