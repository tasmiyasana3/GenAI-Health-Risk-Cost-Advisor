
"""
MODULE NAME
-----------
SECURED FRONTEND ASGI ENTRY POINT

PURPOSE
-------
Serve the restricted Gradio shell and provide server-side
browser authentication through the existing FastAPI backend.

ENVIRONMENT / CONFIGURATION
---------------------------
FRONTEND_COOKIE_SECURE:
    true for HTTPS; false only for local HTTP development.

FRONTEND_ALLOWED_ORIGIN:
    Exact trusted frontend origin, e.g. http://127.0.0.1:7860.

API_BASE_URL:
    Existing backend URL used by FrontendAPIClient.

The in-memory browser registry requires a single frontend
worker. Multi-worker deployment needs shared session storage.

DEPENDENCIES
------------
FastAPI, Gradio, Pydantic, and existing frontend services.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
- Anonymous browser bootstrap.
- Restricted Gradio HTTP boundary.
- Origin-validated login and logout.
- Browser identity rotation after login.
- Server-side credential isolation.
- Correct authentication error classification.
- Backend logout and local cookie invalidation.
- Non-sensitive authentication status responses.

SECURITY NOTES
--------------
- Backend JWT and refresh credentials stay server-side.
- Browser cookies are opaque, HttpOnly and SameSite=Strict.
- Authentication-changing routes require a trusted Origin.
- Backend revocation failures are not reported as success.
- No authenticated Gradio callbacks are enabled here.
- Origin checking is not a complete future Gradio CSRF policy.
- Login rate limiting and production abuse protection
  must be addressed before public deployment.
"""

from __future__ import annotations

import os

import gradio as gr

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from frontend.api_client import FrontendAPIClient, FrontendAPIError
from frontend.auth_coordinator import FrontendAuthenticationCoordinator
from frontend.auth_origin import (
    AuthenticationOriginError,
    AuthenticationOriginGuard,
)
from frontend.browser_session_binding import BrowserSessionBinding
from frontend.gradio_security import GradioSecurityGate
from frontend.http_session import (
    HTTPSessionCookies,
    HTTPSessionSettings,
)
from frontend.session_binding import SessionRegistry


class LoginRequest(BaseModel):
    """Constrain browser-submitted login fields."""

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=1024)


def create_app(
    *,
    secure_cookie: bool | None = None,
    api_client: FrontendAPIClient | None = None,
    allowed_origin: str | None = None,
) -> FastAPI:
    """Build the isolated, restricted frontend ASGI application."""

    if secure_cookie is None:
        raw_setting = os.getenv(
            "FRONTEND_COOKIE_SECURE",
            "true",
        ).strip().lower()

        if raw_setting not in {"true", "false"}:
            raise ValueError(
                "FRONTEND_COOKIE_SECURE must be true or false."
            )

        secure_cookie = raw_setting == "true"

    registry = SessionRegistry()
    binding = BrowserSessionBinding(registry)

    cookies = HTTPSessionCookies(
        binding,
        settings=HTTPSessionSettings(secure=secure_cookie),
    )

    gate = GradioSecurityGate(cookies)

    client = (
        api_client
        if api_client is not None
        else FrontendAPIClient()
    )

    coordinator = FrontendAuthenticationCoordinator(
        api_client=client,
        browser_binding=binding,
    )

    application = FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    def origin_denial(request: Request) -> JSONResponse | None:
        """
        Validate the browser Origin for authentication writes.

        Fail closed when the trusted origin is not configured.
        Never derive the trusted origin from request headers.
        """

        try:
            guard = AuthenticationOriginGuard(
                allowed_origin=allowed_origin
            )
        except ValueError:
            return JSONResponse(
                {
                    "detail": (
                        "Frontend authentication is not configured."
                    )
                },
                status_code=503,
            )

        try:
            guard.validate(request)
        except AuthenticationOriginError:
            return JSONResponse(
                {"detail": "Request origin is not allowed."},
                status_code=403,
            )

        return None

    @application.middleware("http")
    async def enforce_boundary(request: Request, call_next):
        """Preserve the restrictive Phase 5.2.3B Gradio gate."""

        denial = await gate.authorize(request)

        if denial is not None:
            return denial

        return await call_next(request)

    @application.get("/", include_in_schema=False)
    def bootstrap(request: Request):
        """Create an anonymous browser identity when required."""

        identity = cookies.read_identity(request)

        response = RedirectResponse(
            "/ui/",
            status_code=303,
        )

        if identity is None:
            identity = binding.create()
            cookies.set_identity(response, identity)

        return response

    @application.get("/healthz", include_in_schema=False)
    def healthz():
        """Expose a minimal non-sensitive health check."""

        return {"status": "ok"}

    @application.get(
        "/frontend-auth/status",
        include_in_schema=False,
    )
    def authentication_status(request: Request):
        """
        Return only local frontend authentication status.

        Backend authorization remains authoritative.
        """

        identity = cookies.read_identity(request)

        authenticated = (
            identity is not None
            and coordinator.is_authenticated(
                browser_identity=identity
            )
        )

        return JSONResponse(
            {"authenticated": authenticated},
            headers={"Cache-Control": "no-store"},
        )

    @application.post(
        "/frontend-auth/login",
        include_in_schema=False,
    )
    def browser_login(
        request: Request,
        payload: LoginRequest,
    ):
        """
        Authenticate and rotate the browser identity.

        Never return backend access or refresh credentials.
        """

        denial = origin_denial(request)

        if denial is not None:
            return denial

        identity = cookies.read_identity(request)

        if identity is None:
            return JSONResponse(
                {"detail": "Browser session required."},
                status_code=401,
            )

        if coordinator.is_authenticated(
            browser_identity=identity
        ):
            return JSONResponse(
                {
                    "detail": (
                        "Browser is already authenticated."
                    )
                },
                status_code=409,
            )

        try:
            replacement_identity = coordinator.login(
                browser_identity=identity,
                email=payload.email,
                password=payload.password,
            )

        except FrontendAPIError as error:
            # Only an explicit backend 401 represents
            # invalid authentication credentials.
            if error.status_code == 401:
                return JSONResponse(
                    {
                        "detail": (
                            "Authentication could not be completed."
                        )
                    },
                    status_code=401,
                )

            # Includes connection failures, timeouts,
            # backend 5xx, and malformed backend responses.
            return JSONResponse(
                {
                    "detail": (
                        "Authentication service temporarily "
                        "unavailable."
                    )
                },
                status_code=503,
            )

        response = JSONResponse(
            {"authenticated": True},
            status_code=200,
            headers={"Cache-Control": "no-store"},
        )

        cookies.set_identity(
            response,
            replacement_identity,
        )

        return response

    @application.post(
        "/frontend-auth/logout",
        include_in_schema=False,
    )
    def browser_logout(request: Request):
        """
        Attempt backend revocation and remove local browser access.

        An unsuccessful backend logout is not represented
        as confirmed remote revocation.
        """

        denial = origin_denial(request)

        if denial is not None:
            return denial

        identity = cookies.read_identity(request)

        if identity is None:
            response = JSONResponse(
                {"detail": "Browser session required."},
                status_code=401,
            )
            cookies.clear_identity(response)
            return response

        try:
            coordinator.logout(
                browser_identity=identity
            )

        except FrontendAPIError:
            # The coordinator terminates the local binding
            # even if the backend could not revoke the session.
            response = JSONResponse(
                {
                    "detail": (
                        "Logout could not be confirmed."
                    )
                },
                status_code=503,
            )

        except Exception:
            # Preserve a safe browser response if an
            # unexpected cleanup failure occurs.
            binding.terminate(identity)

            response = JSONResponse(
                {
                    "detail": (
                        "Logout could not be confirmed."
                    )
                },
                status_code=503,
            )

        else:
            response = JSONResponse(
                {"authenticated": False},
                status_code=200,
            )

        # Clear the browser cookie on every attempted
        # logout, including failed remote revocation.
        cookies.clear_identity(response)
        response.headers["Cache-Control"] = "no-store"

        return response

    # Gradio is intentionally non-interactive in this phase.
    with gr.Blocks(
        title="Health Advisor — Secure Frontend",
    ) as shell:
        gr.Markdown("# Health Risk & Cost Advisor")
        gr.Markdown(
            "Secure frontend initialization. "
            "Authentication UI and protected operations "
            "are not enabled yet."
        )

    application = gr.mount_gradio_app(
        application,
        shell,
        path="/ui",
    )

    # Expose dependencies to trusted test/server code only.
    # Do not serialize these objects to browser responses.
    application.state.browser_binding = binding
    application.state.session_cookies = cookies
    application.state.auth_coordinator = coordinator

    return application


app = create_app()