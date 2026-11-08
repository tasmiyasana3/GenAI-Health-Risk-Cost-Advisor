
"""
MODULE NAME
-----------
GRADIO PROTECTED CALLBACKS

PURPOSE
-------
Provide a minimal Gradio callback that reauthorizes the
current browser session immediately before executing work.

ENVIRONMENT / CONFIGURATION
---------------------------
Gradio 6.30.0.
Single-worker frontend.
No external services or paid API calls.

DEPENDENCIES
------------
gradio
frontend.gradio_execution_authorizer

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
- Extract the authenticated browser identity from Gradio.
- Extract the current Gradio session hash.
- Reject missing or invalid execution context.
- Reauthorize immediately before performing protected work.
- Avoid exposing backend access tokens to the browser.

ARCHITECTURE / DESIGN
---------------------
Gradio event
    -> Gradio Request
    -> GradioExecutionAuthorizer
    -> TrustedGradioSessionIssuer
    -> BrowserSessionBinding
    -> Authorized callback

SECURITY CONSIDERATIONS
-----------------------
- The request username must originate from the trusted
  Gradio auth_dependency, not user-supplied form input.
- The session hash is always verified against its owner.
- Backend tokens must never appear in callback output.
- This callback is intentionally non-batched, non-streaming,
  and has no cache or validator.
- The HTTP gate must separately authorize event submission.
- This module does not enable any Gradio routes.

NOTES
-----
This is a minimal Phase 5.2.6C callback.
Insurance prediction and policy RAG belong to Phase 5.3.
"""

from __future__ import annotations

import gradio as gr

from frontend.api_client import FrontendAPIError
from frontend.gradio_execution_authorizer import (
    GradioExecutionAuthorizer,
)


class ProtectedGradioCallbacks:
    """Provide authenticated callbacks for the Gradio UI."""

    def __init__(
        self,
        authorizer: GradioExecutionAuthorizer,
    ) -> None:
        self._authorizer = authorizer

    def verify_session(
        self,
        request: gr.Request,
    ) -> str:
        """
        Verify the current browser session before execution.

        Parameters
        ----------
        request:
            Gradio-injected request context.

        Returns
        -------
        str
            A safe confirmation message without credentials.

        Raises
        ------
        FrontendAPIError
            If the browser or session is unauthorized.
        """

        if request is None:
            raise FrontendAPIError(
                "Authenticated request context is required."
            )

        browser_identity = getattr(
            request,
            "username",
            None,
        )

        session_hash = getattr(
            request,
            "session_hash",
            None,
        )

        self._authorizer.authorize(
            browser_identity=browser_identity,
            session_hash=session_hash,
        )

        return "Authenticated session verified."