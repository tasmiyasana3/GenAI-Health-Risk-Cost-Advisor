"""
MODULE NAME
-----------
TRUSTED GRADIO SESSION ISSUER TESTS

PURPOSE
-------
Verify server-issued, browser-bound session hashes and revocation.

DEPENDENCIES
------------
pytest and existing frontend in-memory session components.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
Anonymous rejection, unpredictable issuance, cross-browser denial,
forged hash denial, logout/rotation invalidation, per-browser limits,
explicit revocation, and manager identity preservation.

SECURITY NOTES
--------------
No network, backend, database, LLM, or paid services.
"""

from __future__ import annotations

import pytest

from frontend.api_client import FrontendAPIError
from frontend.browser_session_binding import BrowserSessionBinding
from frontend.gradio_session_issuer import TrustedGradioSessionIssuer
from frontend.session_binding import SessionRegistry
from frontend.session_manager import SessionCredentialManager


@pytest.fixture
def env():
    binding = BrowserSessionBinding(SessionRegistry())
    issuer = TrustedGradioSessionIssuer(binding, max_sessions_per_browser=2)
    yield binding, issuer
    issuer.close_all()
    binding.close_all()


def test_anonymous_cannot_issue(env):
    binding, issuer = env
    with pytest.raises(FrontendAPIError):
        issuer.issue(binding.create())


def test_authenticated_browser_gets_distinct_server_hashes(env):
    binding, issuer = env
    identity = binding.create(SessionCredentialManager())
    first, second = issuer.issue(identity), issuer.issue(identity)
    assert first != second
    assert len(first) >= 32 and len(second) >= 32


def test_issued_hash_resolves_original_manager(env):
    binding, issuer = env
    manager = SessionCredentialManager()
    identity = binding.create(manager)
    assert issuer.verify(identity, issuer.issue(identity)) is manager


def test_forged_hash_is_denied(env):
    binding, issuer = env
    identity = binding.create(SessionCredentialManager())
    with pytest.raises(FrontendAPIError):
        issuer.verify(identity, "attacker-selected-hash")


def test_cross_browser_hash_is_denied(env):
    binding, issuer = env
    alice = binding.create(SessionCredentialManager())
    bob = binding.create(SessionCredentialManager())
    session_hash = issuer.issue(alice)
    with pytest.raises(FrontendAPIError):
        issuer.verify(bob, session_hash)


def test_logout_invalidates_issued_hash(env):
    binding, issuer = env
    identity = binding.create(SessionCredentialManager())
    session_hash = issuer.issue(identity)
    binding.terminate(identity)
    with pytest.raises(FrontendAPIError):
        issuer.verify(identity, session_hash)


def test_login_rotation_invalidates_old_hash(env):
    binding, issuer = env
    old = binding.create(SessionCredentialManager())
    session_hash = issuer.issue(old)
    new = binding.authenticate(old, SessionCredentialManager())
    with pytest.raises(FrontendAPIError):
        issuer.verify(old, session_hash)
    with pytest.raises(FrontendAPIError):
        issuer.verify(new, session_hash)


def test_per_browser_limit_is_enforced(env):
    binding, issuer = env
    identity = binding.create(SessionCredentialManager())
    issuer.issue(identity)
    issuer.issue(identity)
    with pytest.raises(FrontendAPIError):
        issuer.issue(identity)


def test_explicit_revocation_invalidates_hash(env):
    binding, issuer = env
    identity = binding.create(SessionCredentialManager())
    session_hash = issuer.issue(identity)
    issuer.revoke(identity)
    with pytest.raises(FrontendAPIError):
        issuer.verify(identity, session_hash)


def test_close_all_invalidates_hash(env):
    binding, issuer = env
    identity = binding.create(SessionCredentialManager())
    session_hash = issuer.issue(identity)
    issuer.close_all()
    with pytest.raises(FrontendAPIError):
        issuer.verify(identity, session_hash)
