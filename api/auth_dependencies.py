
"""
MODULE NAME
-----------
AUTHENTICATION DEPENDENCIES

PURPOSE
-------
Provide reusable FastAPI dependencies for authenticated API routes.

ENVIRONMENT / CONFIGURATION
---------------------------
Uses the existing JWT signing configuration and PostgreSQL
connection settings.

DEPENDENCIES
------------
FastAPI
services.token_service
services.session_database_service

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Require Bearer access tokens.
2. Validate JWT signatures and claims.
3. Verify active PostgreSQL sessions.
4. Reject revoked or expired sessions.
5. Return verified user/session identity.
6. Handle infrastructure errors safely.

SECURITY NOTES
--------------
A valid JWT alone does not establish an active session.
Never trust user IDs supplied in request bodies or query parameters.
Never expose JWT secrets or database errors to clients.
"""

import logging

from dataclasses import dataclass

from fastapi import Depends, HTTPException
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

from services.session_database_service import is_session_active
from services.token_service import (
    TokenConfigurationError,
    TokenValidationError,
    verify_access_token,
)


# =============================================================================
# CONFIGURATION
# =============================================================================

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(
    auto_error=False,
)


# =============================================================================
# AUTHENTICATED IDENTITY
# =============================================================================

@dataclass(frozen=True)
class AuthenticatedUser:
    """Identity established through JWT and database verification."""

    user_id: str
    session_id: str


# =============================================================================
# AUTHENTICATION DEPENDENCY
# =============================================================================

def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer_scheme
    ),
) -> AuthenticatedUser:
    """Authenticate the caller and verify its active session.

    Returns:
        AuthenticatedUser with verified user and session IDs.

    Raises:
        HTTPException(401): Missing, invalid, or inactive credentials.
        HTTPException(503): Authentication infrastructure unavailable.
    """
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        identity = verify_access_token(credentials.credentials)

    except TokenValidationError as error:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired access token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error

    except TokenConfigurationError as error:
        logger.exception("JWT authentication configuration failure.")

        raise HTTPException(
            status_code=503,
            detail="Authentication is temporarily unavailable.",
        ) from error

    try:
        active = is_session_active(
            session_id=identity["session_id"],
            user_id=identity["user_id"],
        )

    except Exception as error:
        logger.exception("Authentication session lookup failed.")

        raise HTTPException(
            status_code=503,
            detail="Authentication is temporarily unavailable.",
        ) from error

    if not active:
        raise HTTPException(
            status_code=401,
            detail="Session is expired or revoked.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return AuthenticatedUser(
        user_id=identity["user_id"],
        session_id=identity["session_id"],
    )
