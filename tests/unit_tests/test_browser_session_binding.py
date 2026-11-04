
"""
MODULE NAME
-----------
BROWSER SESSION OWNERSHIP BINDING TESTS

PURPOSE
-------
Verify anonymous browser identity creation, authenticated
credential ownership, identity rotation, Gradio session
ownership, expiration, and cleanup.

ENVIRONMENT / CONFIGURATION
---------------------------
Offline pytest execution.
No database, FastAPI server, Gemini API, or network access.

DEPENDENCIES
------------
pytest.
frontend.api_client.
frontend.browser_session_binding.
frontend.session_binding.
frontend.session_manager.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
- Anonymous sessions contain no credential manager.
- Browser identities are unique and unpredictable.
- Existing authenticated creation remains compatible.
- Successful authentication rotates browser identity.
- Old identities cannot resolve credentials.
- Gradio session ownership is isolated by browser.
- Cross-browser access is rejected.
- Unknown and malformed identifiers are rejected.
- Registry expiration invalidates credential access.
- Termination and shutdown remove local ownership.

SECURITY NOTES
--------------
These tests verify in-memory ownership logic only.

They do not establish HTTP cookie authentication,
CSRF protection, queue-event authorization, or
backend document access control.

Those require separate HTTP integration tests.
"""

import pytest

from frontend.api_client import FrontendAPIError
from frontend.browser_session_binding import BrowserSessionBinding
from frontend.session_binding import SessionRegistry
from frontend.session_manager import SessionCredentialManager


@pytest.fixture
def binding():
    """Provide an isolated browser binding for each test."""

    instance = BrowserSessionBinding(SessionRegistry())

    yield instance

    instance.close_all()


def test_anonymous_browser_identity_is_created(binding):
    """Anonymous visitors can receive an identity."""

    identity = binding.create()

    assert isinstance(identity, str)
    assert len(identity) >= 32
    assert binding.exists(identity)


def test_anonymous_browser_has_no_credentials(binding):
    """Creating an anonymous session does not authenticate it."""

    identity = binding.create()

    with pytest.raises(FrontendAPIError):
        binding.resolve(identity)


def test_browser_identities_are_unique(binding):
    """Separate browser sessions receive different identities."""

    first = binding.create()
    second = binding.create()

    assert first != second
    assert len(first) >= 32
    assert len(second) >= 32


def test_existing_authenticated_create_is_compatible(binding):
    """Existing create(manager) callers remain supported."""

    manager = SessionCredentialManager()

    identity = binding.create(manager)

    assert binding.resolve(identity) is manager


def test_two_authenticated_browsers_are_isolated(binding):
    """Each browser resolves only its own manager."""

    alice_manager = SessionCredentialManager()
    bob_manager = SessionCredentialManager()

    alice_identity = binding.create(alice_manager)
    bob_identity = binding.create(bob_manager)

    assert binding.resolve(alice_identity) is alice_manager
    assert binding.resolve(bob_identity) is bob_manager

    assert binding.resolve(alice_identity) is not bob_manager


def test_authentication_rotates_browser_identity(binding):
    """Login replaces the anonymous browser identity."""

    old_identity = binding.create()
    manager = SessionCredentialManager()

    new_identity = binding.authenticate(
        old_identity,
        manager,
    )

    assert new_identity != old_identity
    assert not binding.exists(old_identity)
    assert binding.exists(new_identity)
    assert binding.resolve(new_identity) is manager


def test_old_identity_cannot_resolve_after_login(binding):
    """An invalidated pre-login identity cannot access credentials."""

    old_identity = binding.create()

    binding.authenticate(
        old_identity,
        SessionCredentialManager(),
    )

    with pytest.raises(FrontendAPIError):
        binding.resolve(old_identity)


def test_authentication_rejects_unknown_browser(binding):
    """Unknown browser identities cannot be authenticated."""

    with pytest.raises(FrontendAPIError):
        binding.authenticate(
            "unknown-browser",
            SessionCredentialManager(),
        )


def test_authentication_requires_credential_manager(binding):
    """A credential manager must be supplied for login."""

    identity = binding.create()

    with pytest.raises(TypeError):
        binding.authenticate(identity, None)


def test_gradio_session_can_be_bound_to_owner(binding):
    """A known browser may own a Gradio session."""

    identity = binding.create()

    binding.bind_gradio_session(
        identity,
        "gradio-session-alice",
    )

    binding.verify_gradio_session(
        identity,
        "gradio-session-alice",
    )


def test_rebinding_same_gradio_session_to_same_owner(binding):
    """Binding the same session twice is idempotent."""

    identity = binding.create()

    binding.bind_gradio_session(identity, "session-1")
    binding.bind_gradio_session(identity, "session-1")

    binding.verify_gradio_session(identity, "session-1")


def test_cross_browser_gradio_binding_is_rejected(binding):
    """A second browser cannot claim an owned Gradio session."""

    alice = binding.create()
    bob = binding.create()

    binding.bind_gradio_session(
        alice,
        "alice-gradio-session",
    )

    with pytest.raises(FrontendAPIError):
        binding.bind_gradio_session(
            bob,
            "alice-gradio-session",
        )


def test_cross_browser_gradio_access_is_rejected(binding):
    """A browser cannot verify another browser's Gradio session."""

    alice = binding.create()
    bob = binding.create()

    binding.bind_gradio_session(
        alice,
        "alice-gradio-session",
    )

    with pytest.raises(FrontendAPIError):
        binding.verify_gradio_session(
            bob,
            "alice-gradio-session",
        )


def test_unknown_gradio_session_is_rejected(binding):
    """Unregistered Gradio session hashes are not authorized."""

    identity = binding.create()

    with pytest.raises(FrontendAPIError):
        binding.verify_gradio_session(
            identity,
            "unknown-gradio-session",
        )


@pytest.mark.parametrize(
    "session_hash",
    [None, "", 123],
)
def test_invalid_gradio_session_identifiers_are_rejected(
    binding,
    session_hash,
):
    """Malformed session identifiers are rejected."""

    identity = binding.create()

    with pytest.raises(FrontendAPIError):
        binding.bind_gradio_session(
            identity,
            session_hash,
        )


@pytest.mark.parametrize(
    "identity",
    [None, "", "unknown-browser", 123],
)
def test_unknown_browser_identity_is_rejected(
    binding,
    identity,
):
    """Unknown identities cannot resolve credential managers."""

    with pytest.raises(FrontendAPIError):
        binding.resolve(identity)


def test_login_invalidates_previous_gradio_ownership(binding):
    """Old Gradio ownership is cleared when login rotates identity."""

    old_identity = binding.create()

    binding.bind_gradio_session(
        old_identity,
        "pre-login-session",
    )

    new_identity = binding.authenticate(
        old_identity,
        SessionCredentialManager(),
    )

    with pytest.raises(FrontendAPIError):
        binding.verify_gradio_session(
            new_identity,
            "pre-login-session",
        )


def test_termination_invalidates_browser_identity(binding):
    """Terminated sessions cannot resolve credentials."""

    identity = binding.create(SessionCredentialManager())

    binding.terminate(identity)

    assert not binding.exists(identity)

    with pytest.raises(FrontendAPIError):
        binding.resolve(identity)


def test_termination_clears_gradio_ownership(binding):
    """Terminating a browser removes its Gradio ownership."""

    identity = binding.create()

    binding.bind_gradio_session(
        identity,
        "terminated-session",
    )

    binding.terminate(identity)

    with pytest.raises(FrontendAPIError):
        binding.verify_gradio_session(
            identity,
            "terminated-session",
        )


def test_terminating_one_browser_preserves_another(binding):
    """One browser's termination does not affect another."""

    alice = binding.create(SessionCredentialManager())

    bob_manager = SessionCredentialManager()
    bob = binding.create(bob_manager)

    binding.terminate(alice)

    assert binding.resolve(bob) is bob_manager


def test_registry_expiration_invalidates_credentials():
    """Expired registry handles cannot resolve managers."""

    clock = [1000.0]

    registry = SessionRegistry(
        idle_timeout_seconds=60,
        clock=lambda: clock[0],
    )

    binding = BrowserSessionBinding(registry)

    identity = binding.create(SessionCredentialManager())

    clock[0] += 61

    with pytest.raises(FrontendAPIError):
        binding.resolve(identity)

    with pytest.raises(FrontendAPIError):
        binding.resolve(identity)

    binding.close_all()


def test_close_all_invalidates_every_browser(binding):
    """Shutdown clears anonymous and authenticated sessions."""

    anonymous = binding.create()

    authenticated = binding.create(
        SessionCredentialManager()
    )

    binding.bind_gradio_session(
        anonymous,
        "anonymous-gradio-session",
    )

    binding.close_all()

    assert not binding.exists(anonymous)
    assert not binding.exists(authenticated)

    with pytest.raises(FrontendAPIError):
        binding.resolve(authenticated)

    with pytest.raises(FrontendAPIError):
        binding.verify_gradio_session(
            anonymous,
            "anonymous-gradio-session",
        )