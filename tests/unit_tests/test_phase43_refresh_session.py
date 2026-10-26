
"""
MODULE NAME
-----------
PHASE 4.3D REFRESH SESSION UNIT TESTS

PURPOSE
-------
Verify refresh-token orchestration without a real database.

ENVIRONMENT / CONFIGURATION
---------------------------
Uses pytest monkeypatch with synthetic credentials.

DEPENDENCIES
------------
pytest and services.refresh_session_service.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
Missing and malformed tokens, missing sessions, successful
rotation, rejected rotation, JWT failures, and owner mismatch.

SECURITY NOTES
--------------
All tokens and identifiers are synthetic.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from services import refresh_session_service as service
from services.session_database_service import RefreshRotationStatus


# =============================================================================
# SHARED TEST HELPER
# =============================================================================

def configure_valid_refresh(monkeypatch) -> tuple[str, str]:
    """Configure a synthetic valid refresh-token workflow."""
    session_id = str(uuid4())
    user_id = str(uuid4())

    monkeypatch.setattr(
        service,
        "parse_refresh_token",
        lambda token: (session_id, "old-secret"),
    )

    monkeypatch.setattr(
        service,
        "hash_refresh_secret",
        lambda secret: (
            "a" * 64 if secret == "old-secret" else "b" * 64
        ),
    )

    monkeypatch.setattr(
        service,
        "generate_refresh_secret",
        lambda: "new-secret",
    )

    monkeypatch.setattr(
        service,
        "build_refresh_token",
        lambda session_id, secret: "new-refresh-cookie",
    )

    monkeypatch.setattr(
        service,
        "get_refresh_token_expiry",
        lambda: datetime.now(timezone.utc) + timedelta(days=7),
    )

    monkeypatch.setattr(
        service,
        "get_session",
        lambda session_id: {"user_id": user_id},
    )

    monkeypatch.setattr(
        service,
        "create_access_token",
        lambda user_id, session_id: ("new-access-jwt", 900),
    )

    return session_id, user_id


# =============================================================================
# INVALID INPUTS
# =============================================================================

def test_missing_cookie_is_rejected():
    """Absent refresh credentials must not authenticate."""
    assert service.refresh_session(None) is None
    assert service.refresh_session("") is None


def test_malformed_cookie_is_rejected():
    """Malformed tokens must not reach database rotation."""
    assert service.refresh_session("malformed") is None


def test_missing_session_is_rejected(monkeypatch):
    """A token for a nonexistent session cannot be refreshed."""
    configure_valid_refresh(monkeypatch)

    monkeypatch.setattr(
        service,
        "get_session",
        lambda session_id: None,
    )

    assert service.refresh_session("old-cookie") is None


# =============================================================================
# SUCCESSFUL REFRESH
# =============================================================================

def test_valid_refresh_returns_new_credentials(monkeypatch):
    """Successful rotation returns a new access/refresh pair."""
    _, user_id = configure_valid_refresh(monkeypatch)

    monkeypatch.setattr(
        service,
        "rotate_session_token_checked",
        lambda **kwargs: (
            RefreshRotationStatus.ROTATED,
            user_id,
        ),
    )

    result = service.refresh_session("old-cookie")

    assert result is not None
    assert result.access_token == "new-access-jwt"
    assert result.refresh_token == "new-refresh-cookie"
    assert result.expires_in == 900


# =============================================================================
# FAILED ROTATION
# =============================================================================

@pytest.mark.parametrize(
    "status",
    [
        RefreshRotationStatus.INVALID,
        RefreshRotationStatus.REPLAYED,
    ],
)
def test_failed_rotation_returns_no_credentials(
    monkeypatch,
    status,
):
    """Invalid or replayed tokens must not issue credentials."""
    configure_valid_refresh(monkeypatch)

    monkeypatch.setattr(
        service,
        "rotate_session_token_checked",
        lambda **kwargs: (status, None),
    )

    assert service.refresh_session("old-cookie") is None


def test_jwt_failure_does_not_rotate_session(monkeypatch):
    """JWT signing errors must occur before database rotation."""
    configure_valid_refresh(monkeypatch)

    rotation_calls = []

    def fail_jwt(**kwargs):
        raise RuntimeError("Synthetic JWT signing failure")

    def track_rotation(**kwargs):
        rotation_calls.append(kwargs)
        return RefreshRotationStatus.INVALID, None

    monkeypatch.setattr(
        service,
        "create_access_token",
        fail_jwt,
    )

    monkeypatch.setattr(
        service,
        "rotate_session_token_checked",
        track_rotation,
    )

    with pytest.raises(RuntimeError):
        service.refresh_session("old-cookie")

    assert rotation_calls == []


def test_session_owner_mismatch_is_rejected(monkeypatch):
    """Unexpected ownership mismatch must not return credentials."""
    configure_valid_refresh(monkeypatch)

    monkeypatch.setattr(
        service,
        "rotate_session_token_checked",
        lambda **kwargs: (
            RefreshRotationStatus.ROTATED,
            str(uuid4()),
        ),
    )

    with pytest.raises(RuntimeError):
        service.refresh_session("old-cookie")
