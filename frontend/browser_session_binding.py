
"""
MODULE NAME
-----------
BROWSER SESSION BINDING

PURPOSE
-------
Bind server-issued browser identities to authenticated
credential managers and Gradio session identifiers.

ENVIRONMENT / CONFIGURATION
---------------------------
In-memory, single-process frontend deployment.
No network requests are performed by this module.

DEPENDENCIES
------------
Python standard library.
frontend.api_client.
frontend.session_binding.
frontend.session_manager.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
- Create anonymous browser identities.
- Attach credentials only after authentication.
- Rotate browser identities on login.
- Resolve credentials using trusted browser identities.
- Associate Gradio sessions with browser owners.
- Reject cross-browser Gradio session access.
- Terminate sessions and clear local credentials.

SECURITY NOTES
--------------
- Browser identities are bearer secrets.
- Never expose registry handles or JWTs to the browser.
- Gradio session hashes are not authentication credentials.
- HTTP request authentication must happen separately.
- Cookie theft and CSRF require HTTP-layer defenses.
- In-memory storage requires a single-process deployment.
- Local cleanup does not revoke backend refresh tokens.
"""

from __future__ import annotations

import secrets
import threading

from frontend.api_client import FrontendAPIError
from frontend.session_binding import SessionRegistry
from frontend.session_manager import SessionCredentialManager


class BrowserSessionBinding:
    """Maintain trusted browser-to-credential ownership mappings."""

    def __init__(self, registry: SessionRegistry) -> None:
        self._registry = registry
        self._bindings: dict[str, str | None] = {}
        self._gradio_owners: dict[str, str] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _validate_identity(identity: str | None) -> str:
        """Reject invalid browser identity values."""

        if not isinstance(identity, str) or not identity:
            raise FrontendAPIError(
                "Browser session is unavailable."
            )

        return identity

    def _new_identity(self) -> str:
        """Generate a unique, unpredictable browser identity."""

        identity = secrets.token_urlsafe(32)

        while identity in self._bindings:
            identity = secrets.token_urlsafe(32)

        return identity

    def create(
        self,
        manager: SessionCredentialManager | None = None,
    ) -> str:
        """
        Create an anonymous or authenticated browser identity.

        The optional manager preserves compatibility with
        existing callers. New login flows should use
        create() followed by authenticate().
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

    def exists(self, browser_identity: str | None) -> bool:
        """Check whether a server-issued identity is still registered."""

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
        Attach authenticated credentials and rotate identity.

        The caller must complete backend authentication first.
        The returned identity must replace the previous cookie.
        """

        if not isinstance(manager, SessionCredentialManager):
            raise TypeError(
                "A SessionCredentialManager is required."
            )

        with self._lock:
            identity = self._validate_identity(browser_identity)

            if identity not in self._bindings:
                raise FrontendAPIError(
                    "Browser session is unavailable."
                )

            # Create the replacement before invalidating the old
            # identity, so a registry failure leaves it unchanged.
            new_handle = self._registry.create(manager)
            new_identity = self._new_identity()

            old_handle = self._bindings.pop(identity)

            self._bindings[new_identity] = new_handle

            # Previously owned Gradio sessions must be rebound
            # explicitly after login.
            self._gradio_owners = {
                session_hash: owner
                for session_hash, owner in self._gradio_owners.items()
                if owner != identity
            }

            if old_handle is not None:
                self._registry.remove(old_handle)

            return new_identity

    def resolve(
        self,
        browser_identity: str | None,
    ) -> SessionCredentialManager:
        """Retrieve credentials for a verified browser identity."""

        identity = self._validate_identity(browser_identity)

        with self._lock:
            if identity not in self._bindings:
                raise FrontendAPIError(
                    "Browser session is not authenticated."
                )

            handle = self._bindings[identity]

            if handle is None:
                raise FrontendAPIError(
                    "Browser session is not authenticated."
                )

            try:
                return self._registry.get(handle)
            except FrontendAPIError:
                self._bindings.pop(identity, None)
                self._gradio_owners = {
                    session_hash: owner
                    for session_hash, owner in self._gradio_owners.items()
                    if owner != identity
                }
                raise FrontendAPIError(
                    "Browser session has expired."
                ) from None

    def bind_gradio_session(
        self,
        browser_identity: str,
        session_hash: str,
    ) -> None:
        """
        Associate a Gradio session with a browser.

        The HTTP layer must authenticate browser_identity
        before calling this method.

        This method must not be exposed directly to the browser.
        """

        identity = self._validate_identity(browser_identity)

        if not isinstance(session_hash, str) or not session_hash:
            raise FrontendAPIError(
                "Invalid Gradio session identifier."
            )

        with self._lock:
            if identity not in self._bindings:
                raise FrontendAPIError(
                    "Browser session is unavailable."
                )

            owner = self._gradio_owners.get(session_hash)

            if owner is not None and owner != identity:
                raise FrontendAPIError(
                    "Gradio session ownership mismatch."
                )

            self._gradio_owners[session_hash] = identity

    def verify_gradio_session(
        self,
        browser_identity: str | None,
        session_hash: str | None,
    ) -> None:
        """Reject unknown sessions and cross-browser access."""

        identity = self._validate_identity(browser_identity)

        if not isinstance(session_hash, str) or not session_hash:
            raise FrontendAPIError(
                "Invalid Gradio session identifier."
            )

        with self._lock:
            if identity not in self._bindings:
                raise FrontendAPIError(
                    "Browser session is unavailable."
                )

            if self._gradio_owners.get(session_hash) != identity:
                raise FrontendAPIError(
                    "Gradio session ownership mismatch."
                )

    def terminate(self, browser_identity: str | None) -> None:
        """Invalidate browser ownership and clear local credentials."""

        if not isinstance(browser_identity, str):
            return

        with self._lock:
            handle = self._bindings.pop(browser_identity, None)

            self._gradio_owners = {
                session_hash: owner
                for session_hash, owner in self._gradio_owners.items()
                if owner != browser_identity
            }

            if handle is not None:
                self._registry.remove(handle)

    def close_all(self) -> None:
        """Clear all browser mappings and registered credentials."""

        with self._lock:
            for handle in self._bindings.values():
                if handle is not None:
                    self._registry.remove(handle)

            self._bindings.clear()
            self._gradio_owners.clear()