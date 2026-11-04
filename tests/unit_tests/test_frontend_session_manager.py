
"""
MODULE NAME
-----------
FRONTEND SESSION CREDENTIAL MANAGER UNIT TESTS

PURPOSE
-------
Verify the credential lifecycle for individual frontend
sessions using synthetic authentication data.

ENVIRONMENT / CONFIGURATION
---------------------------
Run locally with pytest.

No running backend, database, API key, or internet
connection is required.

DEPENDENCIES
------------
Python standard library, pytest.
frontend.api_client.
frontend.session_manager.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Successful login.
2. Access-token retrieval before expiration.
3. Refresh shortly before expiration.
4. Refresh-token rotation.
5. Rejection of unauthenticated access.
6. Cleanup after failed refresh.
7. Logout and local credential cleanup.
8. Cleanup after backend logout failure.
9. Separation between manager instances.
10. Permanent closure of a manager.
11. Rejection of duplicate login.
12. Concurrent refresh serialization.
13. Safe credential representations.

SECURITY NOTES
--------------
All credentials are synthetic.
Tests do not contact external services.
Authentication secrets must not be logged.
"""

from __future__ import annotations

import threading
import time

from concurrent.futures import ThreadPoolExecutor

import pytest

from frontend.api_client import (
    AuthenticationCredentials,
    FrontendAPIError,
)

from frontend.session_manager import (
    SessionCredentialManager,
)


# =============================================================================
# TEST HELPERS
# =============================================================================

class FakeClock:
    """Provide deterministic elapsed time for expiration tests."""

    def __init__(self) -> None:
        self.current = 1000.0

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        """Advance synthetic time without sleeping."""

        self.current += seconds


class FakeAuthenticationAPI:
    """
    Simulate the FastAPI authentication contract.

    No HTTP requests are performed.
    """

    def __init__(self) -> None:
        self.login_calls = 0
        self.refresh_calls = 0
        self.logout_calls = 0

        self.fail_refresh = False
        self.fail_logout = False

        self.last_logout_token = None

    def login(
        self,
        email: str,
        password: str,
    ) -> AuthenticationCredentials:
        self.login_calls += 1

        return AuthenticationCredentials(
            access_token=f"access-{email}",
            refresh_token=f"refresh-{email}",
            expires_in=900,
        )

    def refresh(
        self,
        refresh_token: str,
    ) -> AuthenticationCredentials:
        self.refresh_calls += 1

        if self.fail_refresh:
            raise FrontendAPIError(
                "Synthetic refresh failure.",
                status_code=401,
            )

        return AuthenticationCredentials(
            access_token=f"new-access-{self.refresh_calls}",
            refresh_token=f"new-refresh-{self.refresh_calls}",
            expires_in=900,
        )

    def logout(
        self,
        refresh_token: str,
    ) -> None:
        self.logout_calls += 1
        self.last_logout_token = refresh_token

        if self.fail_logout:
            raise FrontendAPIError(
                "Synthetic logout failure.",
                status_code=503,
            )


def make_manager(
    api=None,
    clock=None,
) -> SessionCredentialManager:
    """Construct a manager with synthetic dependencies."""

    return SessionCredentialManager(
        api_client=(
            api if api is not None
            else FakeAuthenticationAPI()
        ),
        clock=clock,
    )


# =============================================================================
# LOGIN AND ACCESS TESTS
# =============================================================================

def test_login_establishes_authenticated_session():
    """Successful login stores a usable access token."""

    api = FakeAuthenticationAPI()
    manager = make_manager(api=api)

    manager.login(
        "alice@example.com",
        "SyntheticPassword123!",
    )

    assert manager.is_authenticated()
    assert manager.get_access_token() == (
        "access-alice@example.com"
    )
    assert api.login_calls == 1


def test_access_token_is_reused_before_expiration():
    """Valid tokens should not trigger unnecessary refreshes."""

    api = FakeAuthenticationAPI()
    clock = FakeClock()

    manager = make_manager(
        api=api,
        clock=clock,
    )

    manager.login(
        "alice@example.com",
        "SyntheticPassword123!",
    )

    clock.advance(100)

    assert manager.get_access_token() == (
        "access-alice@example.com"
    )
    assert api.refresh_calls == 0


def test_access_token_requires_login():
    """An unauthenticated manager cannot return credentials."""

    manager = make_manager()

    with pytest.raises(FrontendAPIError):
        manager.get_access_token()


def test_duplicate_login_is_rejected():
    """An active manager must not be reassigned to another user."""

    api = FakeAuthenticationAPI()
    manager = make_manager(api=api)

    manager.login(
        "alice@example.com",
        "SyntheticPassword123!",
    )

    with pytest.raises(FrontendAPIError):
        manager.login(
            "bob@example.com",
            "SyntheticPassword456!",
        )

    assert api.login_calls == 1


# =============================================================================
# REFRESH TESTS
# =============================================================================

def test_token_refreshes_near_expiration():
    """Near-expiry access must trigger one credential rotation."""

    api = FakeAuthenticationAPI()
    clock = FakeClock()

    manager = make_manager(
        api=api,
        clock=clock,
    )

    manager.login(
        "alice@example.com",
        "SyntheticPassword123!",
    )

    # Original token lifetime is 900 seconds.
    # Default refresh margin is 30 seconds.
    clock.advance(871)

    assert manager.get_access_token() == "new-access-1"
    assert api.refresh_calls == 1


def test_rotated_refresh_token_is_used_for_logout():
    """Logout must use the most recently rotated refresh token."""

    api = FakeAuthenticationAPI()
    clock = FakeClock()

    manager = make_manager(
        api=api,
        clock=clock,
    )

    manager.login(
        "alice@example.com",
        "SyntheticPassword123!",
    )

    clock.advance(871)

    assert manager.get_access_token() == "new-access-1"

    manager.logout()

    assert api.last_logout_token == "new-refresh-1"


def test_failed_refresh_clears_local_credentials():
    """Uncertain refresh results must invalidate local credentials."""

    api = FakeAuthenticationAPI()
    clock = FakeClock()

    manager = make_manager(
        api=api,
        clock=clock,
    )

    manager.login(
        "alice@example.com",
        "SyntheticPassword123!",
    )

    api.fail_refresh = True
    clock.advance(871)

    with pytest.raises(FrontendAPIError):
        manager.get_access_token()

    assert not manager.is_authenticated()

    with pytest.raises(FrontendAPIError):
        manager.get_access_token()


# =============================================================================
# LOGOUT TESTS
# =============================================================================

def test_logout_clears_credentials():
    """Successful logout must remove locally held credentials."""

    api = FakeAuthenticationAPI()
    manager = make_manager(api=api)

    manager.login(
        "alice@example.com",
        "SyntheticPassword123!",
    )

    manager.logout()

    assert not manager.is_authenticated()
    assert api.logout_calls == 1

    with pytest.raises(FrontendAPIError):
        manager.get_access_token()


def test_failed_logout_still_clears_credentials():
    """Local credentials must be cleared even if FastAPI fails."""

    api = FakeAuthenticationAPI()
    manager = make_manager(api=api)

    manager.login(
        "alice@example.com",
        "SyntheticPassword123!",
    )

    api.fail_logout = True

    with pytest.raises(FrontendAPIError):
        manager.logout()

    assert not manager.is_authenticated()


def test_logout_without_login_is_safe():
    """An empty session can be logged out without a backend call."""

    api = FakeAuthenticationAPI()
    manager = make_manager(api=api)

    manager.logout()

    assert api.logout_calls == 0


# =============================================================================
# SESSION ISOLATION TESTS
# =============================================================================

def test_different_managers_keep_credentials_separate():
    """Two independent managers must not share credentials."""

    api = FakeAuthenticationAPI()

    alice = make_manager(api=api)
    bob = make_manager(api=api)

    alice.login(
        "alice@example.com",
        "SyntheticPassword123!",
    )

    bob.login(
        "bob@example.com",
        "SyntheticPassword456!",
    )

    assert alice.get_access_token() == (
        "access-alice@example.com"
    )

    assert bob.get_access_token() == (
        "access-bob@example.com"
    )

    alice.logout()

    assert not alice.is_authenticated()
    assert bob.is_authenticated()

    assert bob.get_access_token() == (
        "access-bob@example.com"
    )


# =============================================================================
# CLEANUP TESTS
# =============================================================================

def test_close_clears_and_disables_session():
    """Closing a manager must prevent subsequent reuse."""

    manager = make_manager()

    manager.login(
        "alice@example.com",
        "SyntheticPassword123!",
    )

    manager.close()

    assert not manager.is_authenticated()

    with pytest.raises(FrontendAPIError):
        manager.get_access_token()

    with pytest.raises(FrontendAPIError):
        manager.login(
            "alice@example.com",
            "SyntheticPassword123!",
        )


def test_close_does_not_claim_backend_revocation():
    """Local cleanup must not silently call backend logout."""

    api = FakeAuthenticationAPI()
    manager = make_manager(api=api)

    manager.login(
        "alice@example.com",
        "SyntheticPassword123!",
    )

    manager.close()

    assert api.logout_calls == 0


# =============================================================================
# CONCURRENCY TESTS
# =============================================================================

def test_concurrent_access_triggers_single_refresh():
    """
    Concurrent access to one expired session must rotate
    the refresh token only once.
    """

    api = FakeAuthenticationAPI()
    clock = FakeClock()

    manager = make_manager(
        api=api,
        clock=clock,
    )

    manager.login(
        "alice@example.com",
        "SyntheticPassword123!",
    )

    clock.advance(871)

    worker_count = 5
    start_barrier = threading.Barrier(worker_count)

    def worker():
        start_barrier.wait(timeout=5)
        return manager.get_access_token()

    with ThreadPoolExecutor(
        max_workers=worker_count
    ) as executor:
        results = list(
            executor.map(
                lambda _: worker(),
                range(worker_count),
            )
        )

    assert results == ["new-access-1"] * worker_count
    assert api.refresh_calls == 1


# =============================================================================
# SECRET HANDLING TESTS
# =============================================================================

def test_manager_repr_does_not_expose_tokens():
    """The manager's representation must not reveal secrets."""

    manager = make_manager()

    manager.login(
        "alice@example.com",
        "SyntheticPassword123!",
    )

    representation = repr(manager)

    assert "access-alice@example.com" not in representation
    assert "refresh-alice@example.com" not in representation