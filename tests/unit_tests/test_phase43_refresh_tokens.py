
"""
PHASE 4.3C REFRESH TOKEN UNIT TESTS

PURPOSE
-------
Verify secure refresh-token generation and parsing.

ENVIRONMENT / CONFIGURATION
---------------------------
No database or external services required.

DEPENDENCIES
------------
pytest and refresh_token_service.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
Token randomness, format, hashing, expiry, and malformed input.

SECURITY NOTES
--------------
Test secrets are synthetic and must never be production secrets.
"""

from uuid import uuid4

import pytest

from services.refresh_token_service import (
    build_refresh_token,
    generate_refresh_secret,
    get_refresh_token_expiry,
    get_refresh_token_lifetime_days,
    hash_refresh_secret,
    parse_refresh_token,
)


def test_generated_secrets_are_distinct():
    """Separate token generations must not reuse secrets."""
    assert generate_refresh_secret() != generate_refresh_secret()


def test_secret_hash_is_sha256():
    """Refresh-token hashes must be lowercase SHA-256 digests."""
    digest = hash_refresh_secret("synthetic-secret")
    assert len(digest) == 64
    assert all(character in "0123456789abcdef" for character in digest)


def test_token_round_trip():
    """A valid token must preserve its session and secret."""
    session_id = str(uuid4())
    secret = generate_refresh_secret()

    token = build_refresh_token(session_id, secret)

    assert parse_refresh_token(token) == (session_id, secret)
    assert secret not in hash_refresh_secret(secret)


@pytest.mark.parametrize(
    "token",
    [
        "",
        "invalid",
        "v2.invalid.invalid",
        "v1.not-a-uuid.secret",
        "v1." + str(uuid4()) + ".short",
        "x" * 300,
    ],
)
def test_invalid_tokens_are_rejected(token):
    """Malformed tokens must fail before database access."""
    with pytest.raises(ValueError):
        parse_refresh_token(token)


def test_default_refresh_lifetime(monkeypatch):
    """Default refresh lifetime must be seven days."""
    monkeypatch.delenv("REFRESH_TOKEN_EXPIRE_DAYS", raising=False)

    assert get_refresh_token_lifetime_days() == 7
    assert get_refresh_token_expiry().tzinfo is not None


@pytest.mark.parametrize("value", ["0", "31", "invalid"])
def test_invalid_lifetime_is_rejected(monkeypatch, value):
    """Unsafe refresh-token lifetime settings must fail."""
    monkeypatch.setenv("REFRESH_TOKEN_EXPIRE_DAYS", value)

    with pytest.raises(ValueError):
        get_refresh_token_lifetime_days()
