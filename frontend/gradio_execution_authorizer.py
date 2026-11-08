
"""
MODULE NAME
-----------
GRADIO EXECUTION AUTHORIZER

PURPOSE
-------
Authorize Gradio operations using a trusted browser identity
and a server-issued, browser-owned Gradio session identifier.

ENVIRONMENT / CONFIGURATION
---------------------------
Single-worker frontend. No external services or paid APIs.

DEPENDENCIES
------------
Existing frontend API error and trusted session issuer.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
- Reject missing or malformed browser identities.
- Reject missing or malformed Gradio session hashes.
- Verify ownership through TrustedGradioSessionIssuer.
- Resolve current server-side access credentials.
- Reject expired or unavailable local credentials.
- Return credentials only to trusted server-side callers.

ARCHITECTURE / DESIGN
---------------------
Authenticated browser cookie
    -> Browser identity
    -> TrustedGradioSessionIssuer.verify()
    -> SessionCredentialManager
    -> Current access token
    -> Authorized server-side execution

SECURITY CONSIDERATIONS
-----------------------
- Never trust a session hash without verifying ownership.
- Never expose backend credentials to the browser.
- Reauthorize at the point of protected execution.
- A valid local credential does not independently prove
  that the remote backend session remains active.
- The backend must still enforce JWT and resource ownership.
- This module does not authorize HTTP routes by itself.

NOTES
-----
This authorizer is a reusable security component.
It must be integrated with the Gradio HTTP gate and
protected callback before enabling event endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass

from frontend.api_client import FrontendAPIError
from frontend.gradio_session_issuer import TrustedGradioSessionIssuer


@dataclass(frozen=True)
class AuthorizedGradioExecution:
    """Credentials available only to trusted server-side code."""

    access_token: str


class GradioExecutionAuthorizer:
    """Verify browser/session ownership before protected execution."""

    def __init__(
        self,
        session_issuer: TrustedGradioSessionIssuer,
    ) -> None:
        self._session_issuer = session_issuer

    def authorize(
        self,
        browser_identity: str | None,
        session_hash: str | None,
    ) -> AuthorizedGradioExecution:
        """
        Revalidate browser ownership and current credentials.

        Raises
        ------
        FrontendAPIError
            When the browser, session, or credentials are invalid.
        """

        if (
            not isinstance(browser_identity, str)
            or not browser_identity.strip()
        ):
            raise FrontendAPIError(
                "Gradio execution is not authorized."
            )

        if (
            not isinstance(session_hash, str)
            or not session_hash.strip()
        ):
            raise FrontendAPIError(
                "Gradio execution is not authorized."
            )

        manager = self._session_issuer.verify(
            browser_identity,
            session_hash,
        )

        access_token = manager.get_access_token()

        if (
            not isinstance(access_token, str)
            or not access_token.strip()
        ):
            raise FrontendAPIError(
                "Gradio credentials are unavailable."
            )

        return AuthorizedGradioExecution(
            access_token=access_token,
        )