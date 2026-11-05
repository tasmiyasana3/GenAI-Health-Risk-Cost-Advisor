
"""
MODULE NAME
-----------
PHASE 5.2.4 AUTHENTICATION COORDINATOR TESTS

PURPOSE
-------
Verify the server-side authentication coordinator before
connecting it to browser-facing HTTP endpoints.

ENVIRONMENT / CONFIGURATION
---------------------------
Runs locally with pytest.
No FastAPI server, PostgreSQL, ChromaDB, Gemini, or network
connection is required.

DEPENDENCIES
------------
pytest
frontend.api_client
frontend.auth_coordinator
frontend.browser_session_binding
frontend.session_binding

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
- Successful authentication rotates browser identity.
- Failed authentication does not authenticate the browser.
- Separate browser sessions retain separate credentials.
- Existing authenticated sessions cannot silently log in again.
- Logout invalidates the local browser binding.
- Backend logout failure still invalidates local access.
- Unknown browser identities cannot initiate authentication.

SECURITY NOTES
--------------
The fake authentication API never makes network requests.

Tokens are synthetic test values. No production credentials
or personally identifiable customer data are used.

These tests do not replace browser HTTP, CSRF, database,
or document authorization integration tests.
"""

from __future__ import annotations

import pytest

from frontend.api_client import (
    AuthenticationCredentials,
    FrontendAPIError,
)
from frontend.auth_coordinator import (
    FrontendAuthenticationCoordinator,
)
from frontend.browser_session_binding import BrowserSessionBinding
from frontend.session_binding import SessionRegistry


class FakeAuthenticationAPI:
    """
    Simulate FastAPI authentication without network access.

    Each successful login receives a distinct synthetic
    credential pair, including when the email is identical.
    """

    def __init__(self) -> None:
        self.login_count = 0
        self.logout_tokens: list[str] = []
        self.fail_logout = False

    def login(
        self,
        email: str,
        password: str,
    ) -> AuthenticationCredentials:
        if password != "valid-test-password":
            raise FrontendAPIError(
                "Invalid credentials.",
                status_code=401,
            )

        self.login_count += 1

        return AuthenticationCredentials(
            access_token=f"access-test-{self.login_count}",
            refresh_token=f"refresh-test-{self.login_count}",
            expires_in=1800,
        )

    def refresh(
        self,
        refresh_token: str,
    ) -> AuthenticationCredentials:
        return AuthenticationCredentials(
            access_token=f"refreshed-{refresh_token}",
            refresh_token=f"rotated-{refresh_token}",
            expires_in=1800,
        )

    def logout(self, refresh_token: str) -> None:
        self.logout_tokens.append(refresh_token)

        if self.fail_logout:
            raise FrontendAPIError(
                "Backend logout unavailable.",
                status_code=503,
            )


@pytest.fixture
def environment():
    """
    Create isolated dependencies for each test.

    The registry and browser bindings are never shared
    between tests.
    """

    api = FakeAuthenticationAPI()
    binding = BrowserSessionBinding(SessionRegistry())

    coordinator = FrontendAuthenticationCoordinator(
        api_client=api,
        browser_binding=binding,
    )

    yield coordinator, binding, api

    binding.close_all()


def authenticate(
    coordinator: FrontendAuthenticationCoordinator,
    binding: BrowserSessionBinding,
    *,
    email: str = "user@example.test",
) -> tuple[str, str]:
    """Create an anonymous identity and authenticate it."""

    old_identity = binding.create()

    new_identity = coordinator.login(
        browser_identity=old_identity,
        email=email,
        password="valid-test-password",
    )

    return old_identity, new_identity


def test_login_rotates_browser_identity(environment):
    """A successful login must replace the anonymous identity."""

    coordinator, binding, _ = environment

    old_identity, new_identity = authenticate(
        coordinator,
        binding,
    )

    assert old_identity != new_identity
    assert not binding.exists(old_identity)
    assert binding.exists(new_identity)

    assert coordinator.is_authenticated(
        browser_identity=new_identity
    )

    assert not coordinator.is_authenticated(
        browser_identity=old_identity
    )


def test_invalid_login_preserves_anonymous_session(environment):
    """Incorrect credentials must not authenticate a browser."""

    coordinator, binding, _ = environment

    identity = binding.create()

    with pytest.raises(FrontendAPIError):
        coordinator.login(
            browser_identity=identity,
            email="user@example.test",
            password="incorrect-password",
        )

    assert binding.exists(identity)

    assert not coordinator.is_authenticated(
        browser_identity=identity
    )


def test_two_users_have_independent_credentials(environment):
    """One browser must never obtain another browser's token."""

    coordinator, binding, _ = environment

    _, identity_a = authenticate(
        coordinator,
        binding,
        email="user-a@example.test",
    )

    _, identity_b = authenticate(
        coordinator,
        binding,
        email="user-b@example.test",
    )

    token_a = coordinator.get_access_token(
        browser_identity=identity_a
    )

    token_b = coordinator.get_access_token(
        browser_identity=identity_b
    )

    assert identity_a != identity_b
    assert token_a == "access-test-1"
    assert token_b == "access-test-2"
    assert token_a != token_b


def test_same_user_separate_logins_have_separate_sessions(
    environment,
):
    """Two logins for the same account must remain independent."""

    coordinator, binding, _ = environment

    _, first = authenticate(
        coordinator,
        binding,
    )

    _, second = authenticate(
        coordinator,
        binding,
    )

    assert first != second

    assert coordinator.get_access_token(
        browser_identity=first
    ) != coordinator.get_access_token(
        browser_identity=second
    )

    coordinator.logout(browser_identity=first)

    assert not coordinator.is_authenticated(
        browser_identity=first
    )

    assert coordinator.is_authenticated(
        browser_identity=second
    )


def test_relogin_does_not_replace_existing_session(environment):
    """An authenticated identity must not silently switch accounts."""

    coordinator, binding, api = environment

    _, identity = authenticate(
        coordinator,
        binding,
    )

    with pytest.raises(FrontendAPIError):
        coordinator.login(
            browser_identity=identity,
            email="another@example.test",
            password="valid-test-password",
        )

    assert api.login_count == 1

    assert coordinator.is_authenticated(
        browser_identity=identity
    )


def test_logout_revokes_and_invalidates_local_session(environment):
    """Logout must call the backend and remove local ownership."""

    coordinator, binding, api = environment

    _, identity = authenticate(
        coordinator,
        binding,
    )

    coordinator.logout(browser_identity=identity)

    assert api.logout_tokens == ["refresh-test-1"]
    assert not binding.exists(identity)

    assert not coordinator.is_authenticated(
        browser_identity=identity
    )


def test_failed_backend_logout_still_invalidates_local_access(
    environment,
):
    """Backend failure must not leave frontend credentials usable."""

    coordinator, binding, api = environment

    _, identity = authenticate(
        coordinator,
        binding,
    )

    api.fail_logout = True

    with pytest.raises(FrontendAPIError):
        coordinator.logout(browser_identity=identity)

    assert not binding.exists(identity)

    assert not coordinator.is_authenticated(
        browser_identity=identity
    )


def test_unknown_browser_cannot_login(environment):
    """Unknown browser identities must be rejected before API login."""

    coordinator, _, api = environment

    with pytest.raises(FrontendAPIError):
        coordinator.login(
            browser_identity="unknown-browser-identity",
            email="user@example.test",
            password="valid-test-password",
        )

    assert api.login_count == 0