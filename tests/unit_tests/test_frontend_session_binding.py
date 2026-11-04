
"""
MODULE NAME
-----------
FRONTEND SESSION REGISTRY UNIT TESTS

PURPOSE
-------
Verify server-side session registry isolation, expiry,
cleanup, and rejection of invalid handles.

ENVIRONMENT / CONFIGURATION
---------------------------
Local pytest execution only.
No running API, database, or Gemini key required.

DEPENDENCIES
------------
pytest.
frontend.api_client.
frontend.session_manager.
frontend.session_binding.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Unique random session handles.
2. Correct manager lookup.
3. Independent manager isolation.
4. Unknown handle rejection.
5. Invalid handle rejection.
6. Idle expiry and credential cleanup.
7. Idle timeout renewal.
8. Explicit removal.
9. Application shutdown cleanup.
10. Invalid timeout configuration.

SECURITY NOTES
--------------
Tests use synthetic credentials.
These tests do not prove browser-session ownership.
That requires a separate authenticated integration test.
"""

import pytest

from frontend.api_client import FrontendAPIError
from frontend.session_binding import SessionRegistry
from frontend.session_manager import SessionCredentialManager


class FakeClock:
    """Provide deterministic monotonic time."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_create_returns_distinct_handles():
    registry = SessionRegistry()

    first = registry.create(SessionCredentialManager())
    second = registry.create(SessionCredentialManager())

    assert first != second
    assert len(first) >= 32
    assert len(second) >= 32


def test_get_returns_correct_manager():
    registry = SessionRegistry()
    manager = SessionCredentialManager()

    handle = registry.create(manager)

    assert registry.get(handle) is manager


def test_two_managers_remain_separate():
    registry = SessionRegistry()

    alice = SessionCredentialManager()
    bob = SessionCredentialManager()

    alice_handle = registry.create(alice)
    bob_handle = registry.create(bob)

    assert registry.get(alice_handle) is alice
    assert registry.get(bob_handle) is bob
    assert registry.get(alice_handle) is not bob


def test_unknown_handle_is_rejected():
    registry = SessionRegistry()

    with pytest.raises(FrontendAPIError):
        registry.get("unknown-handle")


@pytest.mark.parametrize("handle", ["", None, 123])
def test_invalid_handle_is_rejected(handle):
    registry = SessionRegistry()

    with pytest.raises(FrontendAPIError):
        registry.get(handle)


def test_expired_session_is_removed():
    clock = FakeClock()
    registry = SessionRegistry(
        idle_timeout_seconds=60,
        clock=clock,
    )

    manager = SessionCredentialManager()
    handle = registry.create(manager)

    clock.advance(61)

    assert registry.cleanup_expired() == 1

    with pytest.raises(FrontendAPIError):
        registry.get(handle)

    # close() permanently disables the old manager.
    with pytest.raises(FrontendAPIError):
        manager.get_access_token()


def test_access_renews_idle_timeout():
    clock = FakeClock()
    registry = SessionRegistry(
        idle_timeout_seconds=60,
        clock=clock,
    )

    manager = SessionCredentialManager()
    handle = registry.create(manager)

    clock.advance(40)
    assert registry.get(handle) is manager

    clock.advance(40)
    assert registry.get(handle) is manager


def test_remove_clears_registry_entry():
    registry = SessionRegistry()
    manager = SessionCredentialManager()

    handle = registry.create(manager)
    registry.remove(handle)

    with pytest.raises(FrontendAPIError):
        registry.get(handle)


def test_close_all_removes_all_entries():
    registry = SessionRegistry()

    first = registry.create(SessionCredentialManager())
    second = registry.create(SessionCredentialManager())

    registry.close_all()

    for handle in (first, second):
        with pytest.raises(FrontendAPIError):
            registry.get(handle)


@pytest.mark.parametrize("timeout", [0, -1, float("inf")])
def test_invalid_idle_timeout_is_rejected(timeout):
    with pytest.raises(ValueError):
        SessionRegistry(idle_timeout_seconds=timeout)