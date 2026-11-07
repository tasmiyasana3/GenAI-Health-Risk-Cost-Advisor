"""
MODULE NAME
-----------
TRUSTED GRADIO SESSION ISSUER

PURPOSE
-------
Mint server-generated Gradio session identifiers and enforce
browser-bound ownership without trusting client-supplied hashes.

ENVIRONMENT / CONFIGURATION
---------------------------
Single-worker frontend only. In-memory storage; no external services.

DEPENDENCIES
------------
Python standard library; existing frontend browser-session binding.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
- Issue unpredictable, server-owned session identifiers.
- Limit the number of active identifiers per browser.
- Verify ownership and current local authentication on every check.
- Reject forged, anonymous, cross-browser, and revoked identities.
- Support explicit revocation and cleanup.

ARCHITECTURE / DESIGN
---------------------
Authenticated HttpOnly cookie -> BrowserSessionBinding.resolve()
-> TrustedGradioSessionIssuer.issue() -> server-generated hash.
Protected execution must call verify() with the cookie identity and hash.

SECURITY NOTES
--------------
- Never accept a client-chosen hash for enrollment.
- A hash alone is never an authorization credential.
- Login rotation, logout, and local expiry invalidate verification
  because BrowserSessionBinding.resolve() must still succeed.
- The returned hash is browser-visible and must not contain secrets.
- Do not enable Gradio callbacks until its client actually uses the
  issued hash and the execution-time HTTP/queue gate verifies it.
- This does not validate remote backend revocation by itself.
"""

from __future__ import annotations

import secrets
import threading

from frontend.api_client import FrontendAPIError
from frontend.browser_session_binding import BrowserSessionBinding
from frontend.session_manager import SessionCredentialManager


class TrustedGradioSessionIssuer:
    """Mint and verify server-generated, browser-bound session IDs."""

    def __init__(
        self,
        binding: BrowserSessionBinding,
        *,
        max_sessions_per_browser: int = 8,
    ) -> None:
        if max_sessions_per_browser < 1:
            raise ValueError("max_sessions_per_browser must be positive.")
        self._binding = binding
        self._limit = max_sessions_per_browser
        self._owners: dict[str, str] = {}
        self._lock = threading.RLock()

    def issue(self, browser_identity: str) -> str:
        """Issue an unguessable hash only for an authenticated browser."""
        with self._lock:
            self._binding.resolve(browser_identity)
            active = sum(
                owner == browser_identity
                for owner in self._owners.values()
            )
            if active >= self._limit:
                raise FrontendAPIError(
                    "Too many active Gradio sessions."
                )
            session_hash = secrets.token_urlsafe(32)
            while session_hash in self._owners:
                session_hash = secrets.token_urlsafe(32)
            self._owners[session_hash] = browser_identity
            return session_hash

    def verify(
        self,
        browser_identity: str | None,
        session_hash: str | None,
    ) -> SessionCredentialManager:
        """Require matching ownership and current authenticated state."""
        with self._lock:
            if (
                not isinstance(browser_identity, str)
                or not browser_identity
                or not isinstance(session_hash, str)
                or not session_hash
                or self._owners.get(session_hash) != browser_identity
            ):
                raise FrontendAPIError(
                    "Gradio session is not authorized."
                )
            # Authentication is rechecked on each use, including after
            # logout, rotation, and local session expiry.
            return self._binding.resolve(browser_identity)

    def revoke(self, browser_identity: str | None) -> None:
        """Remove every issued session belonging to a browser."""
        if not isinstance(browser_identity, str):
            return
        with self._lock:
            for session_hash, owner in list(self._owners.items()):
                if owner == browser_identity:
                    del self._owners[session_hash]

    def close_all(self) -> None:
        """Discard every issued session during shutdown or testing."""
        with self._lock:
            self._owners.clear()
