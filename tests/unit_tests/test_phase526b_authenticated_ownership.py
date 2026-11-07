
"""
MODULE NAME
-----------
PHASE 5.2.6B AUTHENTICATED GRADIO OWNERSHIP TESTS

PURPOSE
-------
Verify authenticated Gradio session ownership using
the production BrowserSessionBinding implementation.

RESPONSIBILITIES
----------------
- Reject anonymous browser ownership.
- Accept authenticated ownership.
- Reject cross-browser ownership.
- Reject unknown Gradio sessions.
- Invalidate ownership on logout.
- Invalidate ownership after login rotation.
- Reject expired credential registry handles.
- Preserve credential-manager identity.

ARCHITECTURE / DESIGN
---------------------
Tests use real in-memory SessionRegistry and
SessionCredentialManager instances.

No backend, database, Gemini, or external HTTP service
is used.

SECURITY CONSIDERATIONS
-----------------------
These tests establish authenticated ownership behavior.

They do not prove that a client-supplied Gradio session
identifier was securely created by the requesting browser.

That trust boundary must be verified separately before
the production application enables protected callbacks.

NOTES
-----
Run with pytest from the repository root.
"""

from __future__ import annotations

import pytest

from frontend.api_client import FrontendAPIError
from frontend.browser_session_binding import BrowserSessionBinding
from frontend.session_binding import SessionRegistry
from frontend.session_manager import SessionCredentialManager


@pytest.fixture
def binding():
    """Create an isolated browser registry for each test."""

    registry = SessionRegistry()
    browser_binding = BrowserSessionBinding(registry)

    yield browser_binding

    browser_binding.close_all()


def test_anonymous_browser_cannot_bind_protected_session(
    binding,
) -> None:
    """A registered anonymous browser is not authenticated."""

    anonymous = binding.create()

    with pytest.raises(FrontendAPIError):
        binding.bind_authenticated_gradio_session(
            anonymous,
            "test-gradio-session",
        )


def test_authenticated_browser_can_bind_and_verify(
    binding,
) -> None:
    """Authenticated ownership returns the same manager."""

    manager = SessionCredentialManager()
    identity = binding.create(manager)

    binding.bind_authenticated_gradio_session(
        identity,
        "session-alice",
    )

    resolved = binding.verify_authenticated_gradio_session(
        identity,
        "session-alice",
    )

    assert resolved is manager


def test_cross_browser_binding_is_rejected(
    binding,
) -> None:
    """A second authenticated browser cannot claim ownership."""

    alice = binding.create(
        SessionCredentialManager()
    )

    bob = binding.create(
        SessionCredentialManager()
    )

    binding.bind_authenticated_gradio_session(
        alice,
        "session-alice",
    )

    with pytest.raises(FrontendAPIError):
        binding.bind_authenticated_gradio_session(
            bob,
            "session-alice",
        )


def test_cross_browser_verification_is_rejected(
    binding,
) -> None:
    """An authenticated browser cannot use another session."""

    alice = binding.create(
        SessionCredentialManager()
    )

    bob = binding.create(
        SessionCredentialManager()
    )

    binding.bind_authenticated_gradio_session(
        alice,
        "session-alice",
    )

    with pytest.raises(FrontendAPIError):
        binding.verify_authenticated_gradio_session(
            bob,
            "session-alice",
        )


def test_unknown_gradio_session_is_rejected(
    binding,
) -> None:
    """Authentication alone does not authorize a session."""

    identity = binding.create(
        SessionCredentialManager()
    )

    with pytest.raises(FrontendAPIError):
        binding.verify_authenticated_gradio_session(
            identity,
            "never-registered",
        )


def test_logout_invalidates_authenticated_ownership(
    binding,
) -> None:
    """Termination invalidates both credentials and ownership."""

    identity = binding.create(
        SessionCredentialManager()
    )

    binding.bind_authenticated_gradio_session(
        identity,
        "session-before-logout",
    )

    binding.terminate(identity)

    with pytest.raises(FrontendAPIError):
        binding.verify_authenticated_gradio_session(
            identity,
            "session-before-logout",
        )


def test_login_rotation_invalidates_previous_ownership(
    binding,
) -> None:
    """An old Gradio session cannot survive login rotation."""

    old_identity = binding.create(
        SessionCredentialManager()
    )

    binding.bind_authenticated_gradio_session(
        old_identity,
        "session-before-rotation",
    )

    new_identity = binding.authenticate(
        old_identity,
        SessionCredentialManager(),
    )

    with pytest.raises(FrontendAPIError):
        binding.verify_authenticated_gradio_session(
            new_identity,
            "session-before-rotation",
        )


def test_expired_credentials_invalidate_ownership() -> None:
    """Registry expiration must revoke Gradio ownership."""

    clock = [1000.0]

    registry = SessionRegistry(
        idle_timeout_seconds=60,
        clock=lambda: clock[0],
    )

    binding = BrowserSessionBinding(registry)

    try:
        identity = binding.create(
            SessionCredentialManager()
        )

        binding.bind_authenticated_gradio_session(
            identity,
            "session-expiring",
        )

        clock[0] += 61

        with pytest.raises(FrontendAPIError):
            binding.verify_authenticated_gradio_session(
                identity,
                "session-expiring",
            )

    finally:
        binding.close_all()