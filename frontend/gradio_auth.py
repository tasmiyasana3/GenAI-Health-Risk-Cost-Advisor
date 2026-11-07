
"""
MODULE NAME
-----------
GRADIO AUTHENTICATION ADAPTER

PURPOSE
-------
Connect Gradio's supported auth_dependency interface
to the existing server-side browser authentication system.

RESPONSIBILITIES
----------------
- Authenticate Gradio HTTP requests using existing cookies.
- Reject missing, unknown, and unauthenticated identities.
- Reuse the existing BrowserSessionBinding.
- Return a server-validated identity to Gradio.
- Keep backend credentials out of browser responses.

ARCHITECTURE / DESIGN
---------------------
Browser
    |
    | Opaque HttpOnly cookie
    v
HTTPSessionCookies
    |
    | Registered browser identity
    v
BrowserSessionBinding
    |
    | Resolve server-side credentials
    v
GradioAuthenticationAdapter
    |
    | Validated identity only
    v
Gradio auth_dependency

The backend remains authoritative for authentication,
session revocation, and protected resource ownership.

SECURITY CONSIDERATIONS
-----------------------
- A registered anonymous browser is not authenticated.
- Browser identity is checked against server-side state.
- Backend JWT and refresh credentials are never returned.
- The adapter does not authorize Gradio session_hash values.
- Callback and queue authorization require separate checks.
- Authentication failures must not reveal internal details.
- The registry remains single-process.

NOTES
-----
This module does not perform network requests.

It must be used together with the existing restrictive
Gradio HTTP gate, not as a replacement for that gate.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from frontend.api_client import FrontendAPIError
from frontend.browser_session_binding import BrowserSessionBinding
from frontend.http_session import HTTPSessionCookies


@dataclass(frozen=True)
class GradioAuthenticationAdapter:
    """
    Adapt frontend browser authentication to Gradio.

    Gradio calls this object through auth_dependency.

    A successful result is a server-validated browser
    identity. None means authentication was rejected.
    """

    cookies: HTTPSessionCookies
    binding: BrowserSessionBinding

    def __call__(
        self,
        request: Request,
    ) -> str | None:
        """
        Authenticate the browser for a Gradio request.

        Parameters
        ----------
        request:
            Incoming FastAPI/Starlette HTTP request.

        Returns
        -------
        str | None
            Registered authenticated browser identity,
            or None when authentication fails.

        Security
        --------
        Never return backend access tokens, refresh
        tokens, or internal credential-manager handles.
        """

        # Step 1: Validate the opaque cookie against the
        # existing server-side browser registry.
        identity = self.cookies.read_identity(request)

        if identity is None:
            return None

        # Step 2: An anonymous browser may have a valid
        # cookie but no authenticated credential manager.
        # Such a browser must not access protected Gradio.
        try:
            self.binding.resolve(identity)

        except FrontendAPIError:
            return None

        # Step 3: Return only the validated browser identity.
        #
        # This is NOT authorization for arbitrary Gradio
        # session hashes, callbacks, or document resources.
        return identity