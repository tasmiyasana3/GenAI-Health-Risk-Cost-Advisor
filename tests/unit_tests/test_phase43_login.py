
"""Phase 4.3C login unit tests.

PURPOSE
-------
Verify pre-issuance preparation and committed-session response ordering.

ENVIRONMENT / CONFIGURATION
---------------------------
Uses synthetic credentials and pytest monkeypatch; no PostgreSQL.

DEPENDENCIES
------------
pytest, login_service, refresh_token_service.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
Successful issuance and invalid credentials without session writes.

SECURITY NOTES
--------------
No real tokens, users or database connections are used.
"""

from uuid import uuid4

import pytest

from services import login_service
from services.refresh_token_service import hash_refresh_secret, parse_refresh_token


TEST_USER_ID = str(uuid4())


@pytest.fixture(autouse=True)
def token_settings(monkeypatch):
    """Supply valid test-only signing configuration."""
    monkeypatch.setenv('JWT_SECRET_KEY', 'synthetic-test-secret-' * 3)
    monkeypatch.setenv('JWT_ACCESS_TOKEN_EXPIRE_MINUTES', '15')
    monkeypatch.setenv('REFRESH_TOKEN_EXPIRE_DAYS', '7')


def test_successful_login(monkeypatch):
    """Persist the same UUID in both tokens and the session record."""
    events = []
    monkeypatch.setattr(login_service, 'authenticate_user', lambda **kw: TEST_USER_ID)

    def fake_access_token(user_id, session_id):
        events.append('access')
        assert user_id == TEST_USER_ID
        return 'synthetic-jwt', 900

    def fake_create_session(user_id, refresh_token_hash, expires_at, session_id):
        events.append('persist')
        assert user_id == TEST_USER_ID
        assert len(refresh_token_hash) == 64
        return {'session_id': session_id}

    monkeypatch.setattr(login_service, 'create_access_token', fake_access_token)
    monkeypatch.setattr(login_service, 'create_session', fake_create_session)
    result = login_service.login_user('USER@example.com', 'SyntheticPassword123!')
    parsed_id, secret = parse_refresh_token(result.refresh_token)
    assert result.session_id == parsed_id
    assert hash_refresh_secret(secret)
    assert result.expires_in == 900
    assert events == ['access', 'persist']


def test_invalid_credentials_do_not_create_session(monkeypatch):
    """Incorrect credentials cannot issue a session."""
    monkeypatch.setattr(login_service, 'authenticate_user', lambda **kw: None)
    monkeypatch.setattr(
        login_service, 'create_session',
        lambda **kw: pytest.fail('Session must not be created'),
    )
    assert login_service.login_user('unknown@example.com', 'wrong') is None
