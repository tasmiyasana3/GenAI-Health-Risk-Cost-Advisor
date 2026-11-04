
"""
MODULE NAME
-----------
SERVER-SIDE FRONTEND SESSION REGISTRY

PURPOSE
-------
Maintain separate credential-manager instances for frontend
sessions using unpredictable, server-generated handles.

This module provides the server-side registry only.
It does not authenticate a browser or validate Gradio
session_hash values.

ENVIRONMENT / CONFIGURATION
---------------------------
No environment variables are required.

The registry is intended for a single-process local
prototype. Multiple workers require a different design.

DEPENDENCIES
------------
Python standard library.
frontend.session_manager.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Generate unpredictable session handles.
2. Associate one handle with one credential manager.
3. Keep independent session records isolated.
4. Expire idle session records.
5. Clear credentials when a record is removed.
6. Protect registry operations with a lock.
7. Reject unknown, expired, and invalid handles.

SECURITY NOTES
--------------
- Never expose registry handles through Gradio outputs.
- Never accept a browser-provided handle as proof of identity.
- Only trusted server-side integration code may use get().
- Session handles are not substitutes for authentication.
- A verified browser-to-registry binding is still required.
- Local cleanup does not revoke a FastAPI backend session.
- The registry is in-memory and single-process only.
"""

from __future__ import annotations

import secrets
import threading
import time

from dataclasses import dataclass
from typing import Callable

from frontend.api_client import FrontendAPIError
from frontend.session_manager import SessionCredentialManager


DEFAULT_IDLE_TIMEOUT_SECONDS = 1800.0


@dataclass(repr=False)
class _RegistryEntry:
    """Keep one manager and its last-use timestamp."""

    manager: SessionCredentialManager
    last_used: float


class SessionRegistry:
    """
    Store credential managers under server-generated handles.

    Important:
        This class does not determine which browser owns
        a handle. That decision must come from a separately
        verified server-side session binding.
    """

    def __init__(
        self,
        *,
        idle_timeout_seconds: float = (
            DEFAULT_IDLE_TIMEOUT_SECONDS
        ),
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not 0 < idle_timeout_seconds < float("inf"):
            raise ValueError(
                "Idle timeout must be finite and positive."
            )

        self._idle_timeout = float(idle_timeout_seconds)
        self._clock = clock if clock is not None else time.monotonic
        self._entries: dict[str, _RegistryEntry] = {}
        self._lock = threading.RLock()

    def create(
        self,
        manager: SessionCredentialManager,
    ) -> str:
        """
        Register a new manager and return a private handle.

        The handle must remain in trusted server-side code.
        Do not send it to the browser or place it in gr.State.
        """

        if not isinstance(manager, SessionCredentialManager):
            raise TypeError(
                "A SessionCredentialManager is required."
            )

        with self._lock:
            self._remove_expired_locked()

            # 32 cryptographically random bytes produce an
            # unpredictable URL-safe identifier.
            handle = secrets.token_urlsafe(32)

            while handle in self._entries:
                handle = secrets.token_urlsafe(32)

            self._entries[handle] = _RegistryEntry(
                manager=manager,
                last_used=self._clock(),
            )

            return handle

    def get(self, handle: str) -> SessionCredentialManager:
        """
        Retrieve a manager for a trusted server-side caller.

        This method does not authenticate a browser.
        Never call it with an unverified browser identifier.
        """

        if not isinstance(handle, str) or not handle:
            raise FrontendAPIError(
                "Frontend session is unavailable."
            )

        with self._lock:
            self._remove_expired_locked()

            entry = self._entries.get(handle)

            if entry is None:
                raise FrontendAPIError(
                    "Frontend session is unavailable."
                )

            entry.last_used = self._clock()
            return entry.manager

    def remove(self, handle: str) -> None:
        """
        Remove a session and clear its local credentials.

        Does not call FastAPI logout or revoke backend tokens.
        """

        with self._lock:
            entry = self._entries.pop(handle, None)

            if entry is not None:
                entry.manager.close()

    def cleanup_expired(self) -> int:
        """Remove expired records and return their count."""

        with self._lock:
            return self._remove_expired_locked()

    def _remove_expired_locked(self) -> int:
        """Remove idle entries while holding the registry lock."""

        now = self._clock()

        expired_handles = [
            handle
            for handle, entry in self._entries.items()
            if now - entry.last_used >= self._idle_timeout
        ]

        for handle in expired_handles:
            entry = self._entries.pop(handle)
            entry.manager.close()

        return len(expired_handles)

    def close_all(self) -> None:
        """
        Clear all locally stored credentials.

        Intended for controlled application shutdown.
        """

        with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()

            for entry in entries:
                entry.manager.close()