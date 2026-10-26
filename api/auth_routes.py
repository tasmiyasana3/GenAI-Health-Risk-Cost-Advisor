
"""FastAPI routes for user registration."""

import logging

import psycopg
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field

from services.auth_service import hash_password
from services.database_service import create_user


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


class RegisterRequest(BaseModel):
    """Input data required to register a user."""

    email: EmailStr
    password: str = Field(min_length=12, max_length=1024)


class RegisterResponse(BaseModel):
    """Safe user information returned after registration."""

    user_id: str
    email: EmailStr
    created_at: str


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
