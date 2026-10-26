
"""Password hashing, verification and user credential authentication.

Phase 4.2:
    Secure password hashing and verification using Argon2id.

Phase 4.3A:
    Authenticate an existing account using PostgreSQL credentials.

JWT creation and session management are handled by separate services.
"""

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from services.database_service import get_user_by_email


# Recommended Argon2id password hashing configuration.
password_hasher = PasswordHash.recommended()

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_BYTES = 1024


# Precomputed dummy hash used for unknown accounts.
# This reduces straightforward timing differences between unknown
# emails and existing accounts with incorrect passwords.
DUMMY_PASSWORD_HASH = password_hasher.hash(
    "dummy-password-never-used-for-login"
)


def validate_password(password: str) -> None:
    """Validate password input during account registration."""

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
    """Validate and hash a password with Argon2id."""

    validate_password(password)
    return password_hasher.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    """Return True only when the password matches its stored hash."""

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
        # Malformed hashes must not crash the authentication flow.
        return False


def authenticate_user(email: str, password: str) -> str | None:
    """Return the user's UUID when credentials are valid.

    Both an unknown email and an incorrect password return None.
    This avoids revealing whether an email address is registered.

    Database connectivity errors are intentionally not swallowed:
    the API layer will translate them into HTTP 503 responses.
    """

    if not isinstance(email, str) or not isinstance(password, str):
        return None

    # Avoid expensive hashing operations on excessively large inputs.
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return None

    # Reuse the existing Phase 4.2 PostgreSQL lookup.
    user = get_user_by_email(email)

    if user is None:
        # Perform an Argon2id operation even for unknown accounts.
        verify_password(password, DUMMY_PASSWORD_HASH)
        return None

    if not verify_password(
        password,
        user.get("password_hash"),
    ):
        return None

    return str(user["user_id"])
