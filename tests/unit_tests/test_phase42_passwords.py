
"""Phase 4.2: Password hashing unit tests."""

import pytest

from services.auth_service import (
    hash_password,
    verify_password,
)


def test_password_is_hashed_with_argon2id():
    password = "SecurePassword2026!"

    password_hash = hash_password(password)

    assert password_hash.startswith("$argon2id$")
    assert password_hash != password


def test_correct_password_is_verified():
    password = "SecurePassword2026!"
    password_hash = hash_password(password)

    assert verify_password(password, password_hash) is True


def test_incorrect_password_is_rejected():
    password_hash = hash_password("SecurePassword2026!")

    assert verify_password(
        "IncorrectPassword2026!",
        password_hash,
    ) is False


def test_hashes_use_random_salts():
    password = "SecurePassword2026!"

    first_hash = hash_password(password)
    second_hash = hash_password(password)

    assert first_hash != second_hash


def test_short_password_is_rejected():
    with pytest.raises(ValueError):
        hash_password("Short123!")


def test_oversized_password_is_rejected():
    with pytest.raises(ValueError):
        hash_password("a" * 1025)


def test_invalid_stored_hash_is_rejected():
    result = verify_password(
        "SecurePassword2026!",
        "not-a-valid-hash",
    )

    assert result is False
