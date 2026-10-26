
"""Password hashing and verification for user authentication."""

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError


# Argon2id is the recommended password hashing algorithm.
password_hasher = PasswordHash.recommended()

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_BYTES = 1024


def validate_password(password: str) -> None:
    """Validate password length and input type."""

    if not isinstance(password, str):
        raise ValueError("Password must be a string.")

    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must contain at least "
            f"{MIN_PASSWORD_LENGTH} characters."
        )

    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(
            f"Password must not exceed "
            f"{MAX_PASSWORD_BYTES} bytes."
        )


def hash_password(password: str) -> str:
    """Validate and securely hash a password using Argon2id."""

    validate_password(password)

    return password_hasher.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    """Return True only when a password matches a valid stored hash."""

    if not isinstance(password, str):
        return False

    if not isinstance(stored_hash, str) or not stored_hash:
        return False

    try:
        return password_hasher.verify(
            password,
            stored_hash,
        )

    except (ValueError, TypeError, UnknownHashError):
        # Invalid or unsupported password hashes must not crash
        # the authentication workflow.
        return False
