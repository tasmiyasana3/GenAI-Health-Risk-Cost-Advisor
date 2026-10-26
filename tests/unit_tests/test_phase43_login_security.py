
"""Phase 4.3C login security regression tests.

PURPOSE
-------
Ensure no session is inserted when JWT/refresh preparation fails.

ENVIRONMENT / CONFIGURATION
---------------------------
Synthetic user and pytest monkeypatch; no PostgreSQL.

DEPENDENCIES
------------
pytest, login_service, token_service.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
Invalid JWT config, failed signing, failed refresh construction, failed
persistence, and prevention of success responses on failure.

SECURITY NOTES
--------------
Tests must never access the working database or expose real credentials.
"""

from uuid import uuid4

import pytest

from services import login_service
from services.token_service import TokenConfigurationError


@pytest.fixture(autouse=True)
def valid_login(monkeypatch):
    """Set up synthetic credentials and valid token configuration."""
    monkeypatch.setenv('JWT_SECRET_KEY', 'synthetic-test-secret-' * 3)
    monkeypatch.setenv('JWT_ACCESS_TOKEN_EXPIRE_MINUTES', '15')
    monkeypatch.setenv('REFRESH_TOKEN_EXPIRE_DAYS', '7')
    monkeypatch.setattr(
        login_service, 'authenticate_user', lambda **kw: str(uuid4()),
    )


def no_session_insert(monkeypatch):
    """Make any attempted session insertion fail the test."""
    monkeypatch.setattr(
        login_service, 'create_session',
        lambda **kw: pytest.fail('Session must not be inserted'),
    )


def test_invalid_jwt_secret_prevents_session_creation(monkeypatch):
    """Reject invalid signing config before persistence."""
    no_session_insert(monkeypatch)
    monkeypatch.setenv('JWT_SECRET_KEY', 'short')
    with pytest.raises(TokenConfigurationError):
        login_service.login_user('user@example.com', 'SyntheticPassword123!')


def test_invalid_jwt_expiry_prevents_session_creation(monkeypatch):
    """Reject invalid access-token lifetime before persistence."""
    no_session_insert(monkeypatch)
    monkeypatch.setenv('JWT_ACCESS_TOKEN_EXPIRE_MINUTES', '0')
    with pytest.raises(TokenConfigurationError):
        login_service.login_user('user@example.com', 'SyntheticPassword123!')


def test_invalid_refresh_lifetime_prevents_session_creation(monkeypatch):
    """Reject invalid refresh-token lifetime before persistence."""
    no_session_insert(monkeypatch)
    monkeypatch.setenv('REFRESH_TOKEN_EXPIRE_DAYS', '31')
    with pytest.raises(ValueError):
        login_service.login_user('user@example.com', 'SyntheticPassword123!')


def test_jwt_failure_does_not_create_session(monkeypatch):
    """JWT signing errors cannot leave a committed session."""
    no_session_insert(monkeypatch)

    def signing_failure(**kwargs):
        raise RuntimeError('Synthetic JWT signing failure')

    monkeypatch.setattr(login_service, 'create_access_token', signing_failure)
    with pytest.raises(RuntimeError, match='Synthetic JWT signing failure'):
        login_service.login_user('user@example.com', 'SyntheticPassword123!')


def test_refresh_construction_failure_does_not_create_session(monkeypatch):
    """Malformed refresh token preparation cannot persist a session."""
    no_session_insert(monkeypatch)

    def refresh_failure(**kwargs):
        raise RuntimeError('Synthetic refresh construction failure')

    monkeypatch.setattr(login_service, 'build_refresh_token', refresh_failure)
    with pytest.raises(RuntimeError, match='Synthetic refresh construction failure'):
        login_service.login_user('user@example.com', 'SyntheticPassword123!')


def test_database_failure_does_not_return_tokens(monkeypatch):
    """Persistence failure propagates rather than returning credentials."""
    def persistence_failure(**kwargs):
        raise ConnectionError('Synthetic PostgreSQL outage')

    monkeypatch.setattr(login_service, 'create_session', persistence_failure)
    with pytest.raises(ConnectionError, match='Synthetic PostgreSQL outage'):
        login_service.login_user('user@example.com', 'SyntheticPassword123!')
