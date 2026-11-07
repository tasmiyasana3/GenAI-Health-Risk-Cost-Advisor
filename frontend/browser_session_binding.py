
"""
MODULE NAME
-----------
BROWSER SESSION BINDING

PURPOSE
-------
Manage browser identities, server-side credentials, and
ownership of Gradio sessions.

RESPONSIBILITIES
----------------
- Create anonymous browser identities.
- Attach credentials after backend authentication.
- Rotate browser identities during login.
- Resolve authenticated credential managers.
- Maintain Gradio session ownership mappings.
- Enforce authenticated ownership for protected operations.
- Reject cross-browser session access.
- Invalidate ownership on login rotation and logout.
- Clear local credentials when sessions terminate.

ARCHITECTURE / DESIGN
---------------------
Browser
    |
    | Opaque HttpOnly cookie
    v
HTTPSessionCookies
    |
    v
BrowserSessionBinding
    |
    +-- SessionRegistry
    |       |
    |       +-- SessionCredentialManager
    |
    +-- Gradio session ownership registry

The backend remains authoritative for user identity,
session revocation, and document authorization.

SECURITY CONSIDERATIONS
-----------------------
- Browser identities are unpredictable bearer secrets.
- Backend credentials never enter browser-visible state.
- A Gradio session_hash is not proof of authentication.
- Protected operations require authenticated ownership.
- Ownership checks are synchronized using an RLock.
- Login rotation and termination invalidate ownership.
- Only trusted server-side code may establish ownership.
- Never expose binding methods directly as HTTP endpoints.
- The registry is process-local and single-worker only.

NOTES
-----
Legacy binding methods remain for compatibility with
the previously restricted Gradio shell and existing tests.

Protected callbacks must use the authenticated methods.

This module does not independently establish that a
client-supplied Gradio session_hash was created by the
requesting browser. That requires a trusted establishment
mechanism at the HTTP/Gradio integration boundary.

No database, Gemini, or external API calls are made.
"""

from __future__ import annotations

import secrets
import threading

from frontend.api_client import FrontendAPIError
from frontend.session_binding import SessionRegistry
from frontend.session_manager import SessionCredentialManager


class BrowserSessionBinding:
    """
    Maintain browser-to-credential and Gradio ownership
    mappings inside one frontend process.
    """

    def __init__(
        self,
        registry: SessionRegistry,
    ) -> None:
        self._registry = registry

        # Browser identity -> credential registry handle.
        # None represents an anonymous browser.
        self._bindings: dict[str, str | None] = {}

        # Gradio session hash -> browser identity.
        self._gradio_owners: dict[str, str] = {}

        # Protect related registry and ownership operations.
        self._lock = threading.RLock()

    @staticmethod
    def _validate_identity(
        identity: str | None,
    ) -> str:
        """Reject missing or malformed browser identities."""

        if not isinstance(identity, str) or not identity:
            raise FrontendAPIError(
                "Browser session is unavailable."
            )

        return identity

    @staticmethod
    def _validate_gradio_session(
        session_hash: str | None,
    ) -> str:
        """Reject missing or malformed Gradio identifiers."""

        if (
            not isinstance(session_hash, str)
            or not session_hash
        ):
            raise FrontendAPIError(
                "Invalid Gradio session identifier."
            )

        return session_hash

    def _new_identity(self) -> str:
        """
        Generate an unpredictable identity.

        Call only while holding the binding lock.
        """

        identity = secrets.token_urlsafe(32)

        while identity in self._bindings:
            identity = secrets.token_urlsafe(32)

        return identity

    def _remove_gradio_ownership(
        self,
        browser_identity: str,
    ) -> None:
        """
        Remove all Gradio ownership mappings for a browser.

        Call only while holding the binding lock.
        """

        self._gradio_owners = {
            session_hash: owner
            for session_hash, owner in self._gradio_owners.items()
            if owner != browser_identity
        }

    def _resolve_authenticated_locked(
        self,
        browser_identity: str,
    ) -> SessionCredentialManager:
        """
        Resolve authenticated credentials while holding
        the same lock used for ownership operations.

        This prevents local logout from interleaving
        between credential resolution and ownership checks.
        """

        if browser_identity not in self._bindings:
            raise FrontendAPIError(
                "Browser session is not authenticated."
            )

        handle = self._bindings[browser_identity]

        if handle is None:
            raise FrontendAPIError(
                "Browser session is not authenticated."
            )

        try:
            return self._registry.get(handle)

        except FrontendAPIError:
            # An expired registry handle cannot retain
            # browser or Gradio ownership.
            self._bindings.pop(browser_identity, None)

            self._remove_gradio_ownership(
                browser_identity
            )

            raise FrontendAPIError(
                "Browser session has expired."
            ) from None

    def create(
        self,
        manager: SessionCredentialManager | None = None,
    ) -> str:
        """
        Create an anonymous or authenticated browser identity.

        The optional manager preserves compatibility with
        existing internal callers.

        Normal login flows should create an anonymous
        identity first, then call authenticate().
        """

        with self._lock:
            identity = self._new_identity()

            handle = (
                self._registry.create(manager)
                if manager is not None
                else None
            )

            self._bindings[identity] = handle

            return identity

    def exists(
        self,
        browser_identity: str | None,
    ) -> bool:
        """Check whether a browser identity is registered."""

        if not isinstance(browser_identity, str):
            return False

        with self._lock:
            return browser_identity in self._bindings

    def authenticate(
        self,
        browser_identity: str,
        manager: SessionCredentialManager,
    ) -> str:
        """
        Attach credentials and rotate the browser identity.

        The caller must complete backend authentication first.

        Previously owned Gradio sessions are invalidated.
        """

        if not isinstance(
            manager,
            SessionCredentialManager,
        ):
            raise TypeError(
                "A SessionCredentialManager is required."
            )

        with self._lock:
            identity = self._validate_identity(
                browser_identity
            )

            if identity not in self._bindings:
                raise FrontendAPIError(
                    "Browser session is unavailable."
                )

            # Create the replacement before invalidating
            # the existing browser identity.
            new_handle = self._registry.create(manager)
            new_identity = self._new_identity()

            old_handle = self._bindings.pop(identity)

            self._bindings[new_identity] = new_handle

            # Login rotation invalidates previous ownership.
            self._remove_gradio_ownership(identity)

            if old_handle is not None:
                self._registry.remove(old_handle)

            return new_identity

    def resolve(
        self,
        browser_identity: str | None,
    ) -> SessionCredentialManager:
        """
        Retrieve credentials for an authenticated browser.

        Anonymous, unknown, and expired sessions fail closed.
        """

        identity = self._validate_identity(
            browser_identity
        )

        with self._lock:
            return self._resolve_authenticated_locked(
                identity
            )

    def bind_gradio_session(
        self,
        browser_identity: str,
        session_hash: str,
    ) -> None:
        """
        Legacy Gradio ownership registration.

        Preserved for compatibility with the restricted
        frontend shell and existing tests.

        IMPORTANT:
        This method does not require authentication and
        must never authorize protected callbacks.

        The caller must independently authenticate the
        browser and establish a trustworthy Gradio session.
        """

        identity = self._validate_identity(
            browser_identity
        )

        session = self._validate_gradio_session(
            session_hash
        )

        with self._lock:
            if identity not in self._bindings:
                raise FrontendAPIError(
                    "Browser session is unavailable."
                )

            owner = self._gradio_owners.get(session)

            if owner is not None and owner != identity:
                raise FrontendAPIError(
                    "Gradio session ownership mismatch."
                )

            self._gradio_owners[session] = identity

    def verify_gradio_session(
        self,
        browser_identity: str | None,
        session_hash: str | None,
    ) -> None:
        """
        Legacy ownership verification.

        This method checks browser ownership but does
        not require authenticated credentials.

        Protected callbacks must use
        verify_authenticated_gradio_session().
        """

        identity = self._validate_identity(
            browser_identity
        )

        session = self._validate_gradio_session(
            session_hash
        )

        with self._lock:
            if identity not in self._bindings:
                raise FrontendAPIError(
                    "Browser session is unavailable."
                )

            if self._gradio_owners.get(session) != identity:
                raise FrontendAPIError(
                    "Gradio session ownership mismatch."
                )

    def bind_authenticated_gradio_session(
        self,
        browser_identity: str,
        session_hash: str,
    ) -> None:
        """
        Register ownership for an authenticated browser.

        SECURITY PRECONDITION
        ---------------------
        The caller must already have established that
        this Gradio session was created in the trusted
        context of this browser.

        Do not call this method with an arbitrary
        client-supplied session_hash.

        Do not expose this method through an endpoint
        that accepts a session hash from the browser.

        This method enforces authenticated ownership,
        but does not independently prove session creation.
        """

        identity = self._validate_identity(
            browser_identity
        )

        session = self._validate_gradio_session(
            session_hash
        )

        with self._lock:
            # Resolve credentials while holding the
            # ownership lock. Anonymous and expired
            # browser sessions are rejected.
            self._resolve_authenticated_locked(identity)

            owner = self._gradio_owners.get(session)

            if owner is not None and owner != identity:
                raise FrontendAPIError(
                    "Gradio session ownership mismatch."
                )

            self._gradio_owners[session] = identity

    def verify_authenticated_gradio_session(
        self,
        browser_identity: str | None,
        session_hash: str | None,
    ) -> SessionCredentialManager:
        """
        Verify ownership and return server-side credentials.

        Both the browser authentication state and Gradio
        session ownership must be valid.

        This is a local authorization primitive, not a
        substitute for backend authorization.

        Returns
        -------
        SessionCredentialManager
            The existing server-side credential manager.

        Security
        --------
        The returned manager must remain on the server.
        Never serialize it into a Gradio component,
        browser response, or client-visible state.
        """

        identity = self._validate_identity(
            browser_identity
        )

        session = self._validate_gradio_session(
            session_hash
        )

        with self._lock:
            manager = self._resolve_authenticated_locked(
                identity
            )

            if self._gradio_owners.get(session) != identity:
                raise FrontendAPIError(
                    "Gradio session ownership mismatch."
                )

            return manager

    def terminate(
        self,
        browser_identity: str | None,
    ) -> None:
        """
        Invalidate a browser and remove its local credentials.

        Also removes all Gradio ownership mappings.
        """

        if not isinstance(browser_identity, str):
            return

        with self._lock:
            handle = self._bindings.pop(
                browser_identity,
                None,
            )

            self._remove_gradio_ownership(
                browser_identity
            )

            if handle is not None:
                self._registry.remove(handle)

    def close_all(self) -> None:
        """Clear every browser identity and credential handle."""

        with self._lock:
            for handle in self._bindings.values():
                if handle is not None:
                    self._registry.remove(handle)

            self._bindings.clear()
            self._gradio_owners.clear()