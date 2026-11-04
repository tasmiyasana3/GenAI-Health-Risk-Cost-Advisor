
"""
MODULE NAME
-----------
FRONTEND SESSION CREDENTIAL MANAGER

PURPOSE
-------
Manage authentication credentials for one server-side
frontend session.

Coordinate login, access-token retrieval, refresh-token
rotation, logout, and credential cleanup.

The manager is independent of Gradio so its security
behavior can be tested before UI integration.

ENVIRONMENT / CONFIGURATION
---------------------------
No environment variables are required.

The API client handles FastAPI URL and timeout settings.

The refresh margin defaults to 30 seconds and can be
configured when constructing the manager.

DEPENDENCIES
------------
Python standard library.
frontend.api_client.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Store credentials for one frontend session.
2. Return access tokens while they remain valid.
3. Refresh credentials shortly before expiration.
4. Replace rotated credentials atomically.
5. Serialize concurrent refresh operations.
6. Clear credentials after failed refresh.
7. Revoke the backend session during logout.
8. Clear local credentials even if logout fails.
9. Support explicit session cleanup.
10. Avoid exposing secrets in object representations.

SECURITY NOTES
--------------
- One manager instance represents one frontend session.
- Never share one instance across different users.
- Do not place this object in browser-visible Gradio state.
- Do not serialize or log its authentication credentials.
- A lock protects all credential mutations.
- FastAPI remains the authority for authorization.
- Gradio session binding must be verified separately.
- In-memory credentials do not survive process restarts.
"""

from __future__ import annotations

import threading
import time

from dataclasses import dataclass
from typing import Callable, Protocol

from frontend.api_client import (
    AuthenticationCredentials,
    FrontendAPIClient,
    FrontendAPIError,
)


# =============================================================================
# CONSTANTS
# =============================================================================

DEFAULT_REFRESH_MARGIN_SECONDS = 30.0


# =============================================================================
# CLIENT CONTRACT
# =============================================================================

class AuthenticationAPI(Protocol):
    """
    Define the API operations needed by this manager.

    Using a protocol allows unit tests to supply a fake
    API client without network requests.
    """

    def login(
        self,
        email: str,
        password: str,
    ) -> AuthenticationCredentials:
        """Authenticate a user."""

    def refresh(
        self,
        refresh_token: str,
    ) -> AuthenticationCredentials:
        """Rotate authentication credentials."""

    def logout(
        self,
        refresh_token: str,
    ) -> None:
        """Revoke the backend authentication session."""


# =============================================================================
# INTERNAL SESSION RECORD
# =============================================================================

@dataclass(repr=False)
class _SessionCredentials:
    """
    Hold credentials and their local expiration metadata.

    This internal record must never be returned directly
    to frontend components.
    """

    access_token: str
    refresh_token: str
    expires_at: float
    refresh_margin: float


# =============================================================================
# SESSION MANAGER
# =============================================================================

class SessionCredentialManager:
    """
    Manage authentication credentials for one frontend session.

    Create a separate instance for each independently
    authenticated frontend session.

    This class does not identify or authorize browser sessions.
    Secure Gradio-to-manager binding is a separate integration
    responsibility.
    """

    def __init__(
        self,
        api_client: AuthenticationAPI | None = None,
        *,
        refresh_margin_seconds: float = (
            DEFAULT_REFRESH_MARGIN_SECONDS
        ),
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not (
            0 <= refresh_margin_seconds < float("inf")
        ):
            raise ValueError(
                "Refresh margin must be finite "
                "and non-negative."
            )

        self._api_client = (
            api_client
            if api_client is not None
            else FrontendAPIClient()
        )

        self._refresh_margin_seconds = (
            float(refresh_margin_seconds)
        )

        # A monotonic clock measures elapsed time without
        # depending on wall-clock adjustments.
        self._clock = clock if clock is not None else time.monotonic

        # RLock protects both credentials and refresh operations.
        # Only one thread can refresh this session at a time.
        self._lock = threading.RLock()

        self._credentials: _SessionCredentials | None = None
        self._closed = False

    # -------------------------------------------------------------------------
    # INTERNAL HELPERS
    # -------------------------------------------------------------------------

    def _ensure_open(self) -> None:
        """Prevent reuse after explicit session cleanup."""

        if self._closed:
            raise FrontendAPIError(
                "This frontend session is no longer available."
            )

    def _store_credentials(
        self,
        credentials: AuthenticationCredentials,
    ) -> None:
        """
        Validate and store a complete credential pair.

        The caller must hold the session lock.
        """

        if (
            not isinstance(credentials.access_token, str)
            or not credentials.access_token
            or not isinstance(credentials.refresh_token, str)
            or not credentials.refresh_token
            or type(credentials.expires_in) is not int
            or credentials.expires_in <= 0
        ):
            raise FrontendAPIError(
                "Incomplete authentication credentials."
            )

        lifetime = float(credentials.expires_in)

        # For short-lived tokens, avoid refreshing immediately
        # simply because the configured margin is larger than
        # the token's entire lifetime.
        effective_margin = min(
            self._refresh_margin_seconds,
            lifetime / 2.0,
        )

        self._credentials = _SessionCredentials(
            access_token=credentials.access_token,
            refresh_token=credentials.refresh_token,
            expires_at=self._clock() + lifetime,
            refresh_margin=effective_margin,
        )

    def _clear_credentials(self) -> None:
        """
        Remove locally held credentials.

        The caller must hold the session lock.
        """

        self._credentials = None

    # -------------------------------------------------------------------------
    # LOGIN
    # -------------------------------------------------------------------------

    def login(
        self,
        email: str,
        password: str,
    ) -> None:
        """
        Authenticate and establish this manager's session.

        A manager with an active login cannot be reused for
        another login. The existing session must be logged
        out first, or a new manager must be created.
        """

        with self._lock:
            self._ensure_open()

            if self._credentials is not None:
                raise FrontendAPIError(
                    "This frontend session is already authenticated."
                )

            credentials = self._api_client.login(
                email,
                password,
            )

            self._store_credentials(credentials)

    # -------------------------------------------------------------------------
    # SESSION STATUS
    # -------------------------------------------------------------------------

    def is_authenticated(self) -> bool:
        """
        Report whether local credentials are available.

        This does not verify backend session revocation.
        FastAPI performs authorization on protected requests.
        """

        with self._lock:
            return (
                not self._closed
                and self._credentials is not None
            )

    # -------------------------------------------------------------------------
    # ACCESS TOKEN RETRIEVAL
    # -------------------------------------------------------------------------

    def get_access_token(self) -> str:
        """
        Return a valid or freshly refreshed access token.

        Refresh is serialized by the session lock, preventing
        concurrent operations from rotating the same refresh
        token independently.

        The token is intended only for trusted server-side
        API communication.
        """

        with self._lock:
            self._ensure_open()

            credentials = self._credentials

            if credentials is None:
                raise FrontendAPIError(
                    "Authentication is required."
                )

            refresh_at = (
                credentials.expires_at
                - credentials.refresh_margin
            )

            if self._clock() < refresh_at:
                return credentials.access_token

            try:
                refreshed = self._api_client.refresh(
                    credentials.refresh_token
                )

                # Replace the entire credential pair together.
                self._store_credentials(refreshed)

            except Exception:
                # A failed or uncertain refresh may have consumed
                # the old refresh token. Do not reuse it.
                self._clear_credentials()
                raise

            assert self._credentials is not None
            return self._credentials.access_token

    # -------------------------------------------------------------------------
    # LOGOUT
    # -------------------------------------------------------------------------

    def logout(self) -> None:
        """
        Request backend logout and clear local credentials.

        Local credentials are always cleared, even if the
        backend request fails.

        A failed backend logout is not proof of revocation.
        The caller must not report successful server-side
        revocation when an error occurs.
        """

        with self._lock:
            self._ensure_open()

            credentials = self._credentials

            if credentials is None:
                return

            try:
                self._api_client.logout(
                    credentials.refresh_token
                )
            finally:
                self._clear_credentials()

    # -------------------------------------------------------------------------
    # SESSION CLEANUP
    # -------------------------------------------------------------------------

    def close(self) -> None:
        """
        Clear local credentials and permanently close the manager.

        This is local cleanup only. It does not call FastAPI
        logout and therefore does not revoke a backend session.

        Use logout for an explicit user-initiated sign-out.
        """

        with self._lock:
            self._clear_credentials()
            self._closed = True