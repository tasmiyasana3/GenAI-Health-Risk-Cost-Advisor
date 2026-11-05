
"""
MODULE NAME
-----------
FRONTEND AUTHENTICATION COORDINATOR

PURPOSE
-------
Coordinate FastAPI authentication with frontend browser-session
ownership, without exposing backend credentials to the browser.

ENVIRONMENT / CONFIGURATION
---------------------------
Uses the existing FrontendAPIClient configuration and the
single-process BrowserSessionBinding implementation.

No additional environment variables or paid services.

DEPENDENCIES
------------
Python standard library logging.
frontend.api_client.
frontend.browser_session_binding.
frontend.session_manager.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
- Establish authenticated frontend sessions.
- Rotate browser identities after successful login.
- Keep backend credentials server-side.
- Resolve credentials for trusted server-side requests.
- Handle failed login and partial authentication failures.
- Attempt compensating backend logout after binding failure.
- Preserve the original failure when rollback also fails.
- Invalidate local sessions on logout.

SECURITY NOTES
--------------
- Browser identities are not JWT access tokens.
- Do not expose credentials through Gradio state or HTTP.
- HTTP routes must independently enforce cookie validation,
  origin/CSRF protection, and appropriate abuse controls.
- FastAPI remains the authentication authority.
- Backend logout failure does not prove revocation.
- This coordinator does not authorize document ownership.
"""

from __future__ import annotations

import logging

from frontend.api_client import (
    FrontendAPIClient,
    FrontendAPIError,
)
from frontend.browser_session_binding import BrowserSessionBinding
from frontend.session_manager import SessionCredentialManager


logger = logging.getLogger(__name__)


class FrontendAuthenticationCoordinator:
    """
    Orchestrate authentication for trusted frontend callers.

    Authentication state remains in existing per-session
    credential managers, not in a global user variable.
    """

    def __init__(
        self,
        *,
        api_client: FrontendAPIClient,
        browser_binding: BrowserSessionBinding,
    ) -> None:
        self._api_client = api_client
        self._browser_binding = browser_binding

    def login(
        self,
        *,
        browser_identity: str,
        email: str,
        password: str,
    ) -> str:
        """
        Authenticate and rotate the browser identity.

        Returns only the new opaque browser identity.

        The HTTP layer must set the replacement cookie.

        If browser binding fails after successful backend
        authentication, attempt backend revocation and always
        discard local credentials.
        """

        if not self._browser_binding.exists(browser_identity):
            raise FrontendAPIError(
                "Browser session is unavailable."
            )

        # An already-authenticated browser must explicitly
        # log out rather than silently replace its account.
        try:
            self._browser_binding.resolve(browser_identity)
        except FrontendAPIError as exc:
            if str(exc) != "Browser session is not authenticated.":
                raise
        else:
            raise FrontendAPIError(
                "Browser session is already authenticated."
            )

        manager = SessionCredentialManager(
            api_client=self._api_client,
        )

        try:
            manager.login(
                email=email,
                password=password,
            )

            return self._browser_binding.authenticate(
                browser_identity,
                manager,
            )

        except Exception:
            # If backend login succeeded, a backend session
            # may exist even though browser binding failed.
            #
            # Preserve the original exception. A second
            # exception during rollback must not mask it.
            if manager.is_authenticated():
                try:
                    manager.logout()
                except Exception:
                    # Do not log raw exception text: external
                    # error messages may contain sensitive data.
                    logger.warning(
                        "Backend authentication rollback failed; "
                        "remote session revocation is unconfirmed."
                    )

            # Local credentials are cleared even if remote
            # revocation could not be confirmed.
            manager.close()
            raise

    def get_access_token(
        self,
        *,
        browser_identity: str,
    ) -> str:
        """
        Return a token for trusted server-side API calls.

        The existing credential manager handles refresh.
        Never send this result to a browser response.
        """

        manager = self._browser_binding.resolve(
            browser_identity
        )
        return manager.get_access_token()

    def is_authenticated(
        self,
        *,
        browser_identity: str,
    ) -> bool:
        """
        Check whether local frontend credentials exist.

        Backend session validity is checked by FastAPI
        when protected requests are made.
        """

        try:
            manager = self._browser_binding.resolve(
                browser_identity
            )
        except FrontendAPIError:
            return False

        return manager.is_authenticated()

    def logout(
        self,
        *,
        browser_identity: str,
    ) -> None:
        """
        Attempt backend revocation and remove local binding.

        Even if backend logout fails, local access is
        invalidated. The HTTP caller must clear the cookie.

        Backend failures are propagated to the caller.
        """

        try:
            manager = self._browser_binding.resolve(
                browser_identity
            )
            manager.logout()
        finally:
            self._browser_binding.terminate(
                browser_identity
            )
