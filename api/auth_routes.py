
"""
AUTHENTICATION API ROUTES

PURPOSE
-------
Expose registration and secure password-login endpoints.

ENVIRONMENT / CONFIGURATION
---------------------------
COOKIE_SECURE controls whether refresh cookies require HTTPS.
Use false for local HTTP development and true for HTTPS deployment.
Requires PostgreSQL and JWT configuration through existing services.

DEPENDENCIES
------------
FastAPI, Pydantic, psycopg, auth_service, database_service,
and login_service.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
Validate registration and login requests, return safe HTTP errors,
issue access tokens, and set HttpOnly refresh cookies.

SECURITY NOTES
--------------
Never return refresh tokens in JSON or log passwords.
Use generic invalid-credential errors, restricted cookie paths,
no-store cache headers, and secure cookies in production.
"""

import logging
import os

import psycopg

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field

from services.auth_service import hash_password
from services.database_service import create_user
from services.login_service import login_user
from services.refresh_token_service import get_refresh_token_lifetime_days


# =============================================================================
# ROUTER AND LOGGING
# =============================================================================

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)

REFRESH_COOKIE_NAME = "refresh_token"


# =============================================================================
# REQUEST AND RESPONSE MODELS
# =============================================================================

class RegisterRequest(BaseModel):
    """Input required to create a registered user account."""

    email: EmailStr
    password: str = Field(min_length=12, max_length=1024)


class RegisterResponse(BaseModel):
    """Non-sensitive account information returned after registration."""

    user_id: str
    email: EmailStr
    created_at: str


class LoginRequest(BaseModel):
    """Email and password supplied by an existing user."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class LoginResponse(BaseModel):
    """Short-lived access-token response without refresh secrets."""

    access_token: str
    token_type: str
    expires_in: int


# =============================================================================
# COOKIE CONFIGURATION
# =============================================================================

def get_cookie_secure() -> bool:
    """Validate the secure-cookie configuration."""
    value = os.getenv("COOKIE_SECURE", "true").strip().lower()

    if value not in {"true", "false"}:
        raise ValueError("COOKIE_SECURE must be true or false.")

    return value == "true"


# =============================================================================
# REGISTRATION
# =============================================================================

@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=201,
    summary="Register a new user",
)
def register_user(request: RegisterRequest):
    """Validate credentials and create a user account."""
    normalized_email = str(request.email).strip().lower()

    try:
        password_hash = hash_password(request.password)

        user = create_user(
            email=normalized_email,
            password_hash=password_hash,
        )

        return {
            "user_id": str(user["user_id"]),
            "email": user["email"],
            "created_at": user["created_at"].isoformat(),
        }

    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error

    except psycopg.errors.UniqueViolation as error:
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists.",
        ) from error

    except psycopg.Error as error:
        logger.exception("Database error during registration.")

        raise HTTPException(
            status_code=503,
            detail="Registration is temporarily unavailable.",
        ) from error


# =============================================================================
# LOGIN
# =============================================================================

@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Sign in to an existing account",
)
def login(
    request: LoginRequest,
    response: Response,
):
    """Authenticate credentials and issue an access/refresh pair."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"

    try:
        # Validate cookie settings before issuing a database session.
        secure_cookie = get_cookie_secure()
        refresh_days = get_refresh_token_lifetime_days()

        result = login_user(
            email=str(request.email),
            password=request.password,
        )

        if result is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        response.set_cookie(
            key=REFRESH_COOKIE_NAME,
            value=result.refresh_token,
            max_age=refresh_days * 86400,
            httponly=True,
            secure=secure_cookie,
            samesite="strict",
            path="/auth",
        )

        return {
            "access_token": result.access_token,
            "token_type": "bearer",
            "expires_in": result.expires_in,
        }

    except HTTPException:
        raise

    except psycopg.Error as error:
        logger.exception("Database error during login.")

        raise HTTPException(
            status_code=503,
            detail="Login is temporarily unavailable.",
        ) from error

    except Exception as error:
        logger.exception("Unexpected login service failure.")

        raise HTTPException(
            status_code=503,
            detail="Login is temporarily unavailable.",
        ) from error
