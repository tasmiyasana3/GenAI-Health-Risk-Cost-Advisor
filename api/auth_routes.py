
"""
MODULE NAME
-----------
AUTHENTICATION API ROUTES

PURPOSE
-------
Provide registration, password login, and refresh-token rotation
endpoints for the Insurance Cost and Policy RAG application.

ENVIRONMENT / CONFIGURATION
---------------------------
COOKIE_SECURE:
    true for HTTPS deployments; false for local HTTP development.

AUTH_ALLOWED_ORIGINS:
    Optional comma-separated list of exact trusted frontend origins.
    If unset, the API's own origin is trusted.

REFRESH_TOKEN_EXPIRE_DAYS:
    Existing refresh-token lifetime setting.

DEPENDENCIES
------------
FastAPI, Pydantic, psycopg, and existing authentication services.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Register users with hashed passwords.
2. Authenticate existing users.
3. Return short-lived access JWTs.
4. Set restricted HttpOnly refresh cookies.
5. Validate refresh request origins.
6. Rotate refresh cookies and issue replacement JWTs.
7. Return generic authentication and infrastructure errors.

SECURITY NOTES
--------------
Never return refresh tokens in JSON.
Never log plaintext tokens or passwords.
Use no-store response headers.
Use Secure cookies in HTTPS deployments.
Restrict refresh requests to trusted browser origins.
"""

import logging
import os

from urllib.parse import urlsplit

import psycopg

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field

from services.auth_service import hash_password
from services.database_service import create_user
from services.login_service import login_user
from services.refresh_session_service import refresh_session
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
    """Input required to create a user account."""

    email: EmailStr
    password: str = Field(min_length=12, max_length=1024)


class RegisterResponse(BaseModel):
    """Non-sensitive registration response."""

    user_id: str
    email: EmailStr
    created_at: str


class LoginRequest(BaseModel):
    """Credentials supplied by an existing user."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class LoginResponse(BaseModel):
    """Access-token response without refresh secrets."""

    access_token: str
    token_type: str
    expires_in: int


# =============================================================================
# COOKIE CONFIGURATION
# =============================================================================

def get_cookie_secure() -> bool:
    """Read and validate the Secure-cookie setting."""
    value = os.getenv("COOKIE_SECURE", "true").strip().lower()

    if value not in {"true", "false"}:
        raise ValueError("COOKIE_SECURE must be true or false.")

    return value == "true"


def set_refresh_cookie(
    response: Response,
    refresh_token: str,
    secure_cookie: bool,
    refresh_days: int,
) -> None:
    """Issue a restricted HttpOnly refresh-token cookie."""
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=refresh_days * 86400,
        httponly=True,
        secure=secure_cookie,
        samesite="strict",
        path="/auth",
    )


# =============================================================================
# REFRESH REQUEST ORIGIN VALIDATION
# =============================================================================

def normalize_origin(value: str) -> str:
    """Normalize a trusted HTTP(S) origin for exact comparison."""
    parsed = urlsplit(value.strip())

    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Invalid authentication origin.")

    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("Invalid authentication origin.") from error

    hostname = parsed.hostname.lower()

    if ":" in hostname:
        hostname = f"[{hostname}]"

    default_port = (
        (parsed.scheme == "http" and port == 80)
        or (parsed.scheme == "https" and port == 443)
    )

    port_suffix = (
        f":{port}"
        if port is not None and not default_port
        else ""
    )

    return f"{parsed.scheme}://{hostname}{port_suffix}"


def validate_refresh_origin(request: Request) -> None:
    """Reject refresh requests from untrusted browser origins.

    Origin takes precedence when supplied. If Origin is absent,
    a same-origin Fetch Metadata header is required.

    This endpoint intentionally fails closed when neither browser
    origin signal is available.
    """
    configured = os.getenv("AUTH_ALLOWED_ORIGINS", "").strip()

    if configured:
        allowed_origins = {
            normalize_origin(item)
            for item in configured.split(",")
        }
    else:
        allowed_origins = {
            normalize_origin(str(request.base_url).rstrip("/"))
        }

    origin = request.headers.get("origin")

    if origin is not None:
        try:
            normalized_origin = normalize_origin(origin)
        except ValueError:
            normalized_origin = None

        if normalized_origin not in allowed_origins:
            raise HTTPException(
                status_code=403,
                detail="Refresh request origin is not allowed.",
            )

        return

    if request.headers.get("sec-fetch-site") != "same-origin":
        raise HTTPException(
            status_code=403,
            detail="Refresh request origin is not allowed.",
        )


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
    """Validate credentials and create a registered account."""
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
    """Authenticate credentials and issue access/refresh tokens."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"

    try:
        # Validate settings before creating a database session.
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

        set_refresh_cookie(
            response=response,
            refresh_token=result.refresh_token,
            secure_cookie=secure_cookie,
            refresh_days=refresh_days,
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


# =============================================================================
# PHASE 4.3D - REFRESH TOKEN ROTATION
# =============================================================================

@router.post(
    "/refresh",
    response_model=LoginResponse,
    summary="Rotate refresh token and issue a new access token",
)
def refresh_access_token(
    request: Request,
    response: Response,
):
    """Rotate a refresh cookie and return a replacement access JWT."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"

    try:
        # Validate configuration before rotating database state.
        secure_cookie = get_cookie_secure()
        refresh_days = get_refresh_token_lifetime_days()

        # Reject untrusted browser origins before reading the cookie.
        validate_refresh_origin(request)

        existing_token = request.cookies.get(
            REFRESH_COOKIE_NAME
        )

        result = refresh_session(existing_token)

        if result is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired refresh token.",
            )

        set_refresh_cookie(
            response=response,
            refresh_token=result.refresh_token,
            secure_cookie=secure_cookie,
            refresh_days=refresh_days,
        )

        return {
            "access_token": result.access_token,
            "token_type": "bearer",
            "expires_in": result.expires_in,
        }

    except HTTPException:
        raise

    except Exception as error:
        logger.exception("Refresh service failure.")

        raise HTTPException(
            status_code=503,
            detail="Token refresh is temporarily unavailable.",
        ) from error
