
"""
MODULE NAME
-----------
SECURED FRONTEND ASGI ENTRY POINT

PURPOSE
-------
Serve the restricted Gradio shell and provide browser
authentication through the existing FastAPI backend.

Phase 5.2.5B provides interactive registration, login,
status, and logout through a server-controlled browser
identity. It also enforces bounded authentication bodies.

ENVIRONMENT / CONFIGURATION
---------------------------
FRONTEND_COOKIE_SECURE:
    true for HTTPS; false only for local HTTP development.

FRONTEND_ALLOWED_ORIGIN:
    Exact trusted frontend origin, for example:
    http://127.0.0.1:7860

API_BASE_URL:
    Existing FastAPI backend URL.

The in-memory browser registry supports independent
browser sessions within one frontend worker.

Shared session storage is required before deploying
multiple frontend workers.

DEPENDENCIES
------------
FastAPI, Gradio, Pydantic, Starlette, and existing
frontend authentication and security modules.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
- Anonymous browser bootstrap.
- Restricted Gradio HTTP boundary.
- Registration through the existing backend.
- Origin-validated authentication writes.
- Bounded authentication request bodies.
- Browser identity rotation after login.
- Server-side credential isolation.
- Authentication error classification.
- Logout and browser-cookie invalidation.
- Security headers and CSP nonce generation.

SECURITY NOTES
--------------
- JWT and refresh credentials remain server-side.
- Browser identity cookies are HttpOnly and SameSite=Strict.
- Authentication writes require a trusted Origin.
- Authentication bodies are limited before JSON parsing.
- Private Starlette request attributes are not modified.
- Gradio event, upload, queue, and file routes stay disabled.
- Failed backend revocation is not reported as success.
- Rate limiting is required before public deployment.
- This implementation is not horizontally scalable yet.
"""

from __future__ import annotations

import os
import secrets

import gradio as gr

from fastapi import FastAPI, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)
from pydantic import BaseModel, Field

from frontend.api_client import (
    FrontendAPIClient,
    FrontendAPIError,
)
from frontend.auth_coordinator import (
    FrontendAuthenticationCoordinator,
)
from frontend.auth_origin import (
    AuthenticationOriginError,
    AuthenticationOriginGuard,
)
from frontend.auth_page import render_auth_page
from frontend.browser_session_binding import BrowserSessionBinding
from frontend.gradio_auth import GradioAuthenticationAdapter
from frontend.gradio_session_issuer import TrustedGradioSessionIssuer
from frontend.gradio_execution_authorizer import GradioExecutionAuthorizer
from frontend.gradio_security import GradioSecurityGate
from frontend.http_session import (
    HTTPSessionCookies,
    HTTPSessionSettings,
)
from frontend.session_binding import SessionRegistry


MAX_AUTH_REQUEST_BYTES = 4096

AUTH_WRITE_PATHS = frozenset(
    {
        "/frontend-auth/login",
        "/frontend-auth/register",
        "/frontend-auth/logout",
    }
)


class AuthenticationBodyLimitMiddleware:
    """
    Limit authentication request bodies using the ASGI protocol.

    The middleware reads no more than the configured maximum
    plus one byte before deciding whether to reject a request.

    Accepted bodies are replayed through an ASGI receive
    callable. No private Starlette request attributes are used.

    Other application routes pass through unchanged.
    """

    def __init__(
        self,
        app,
        max_body_bytes: int = MAX_AUTH_REQUEST_BYTES,
    ) -> None:
        if max_body_bytes < 1:
            raise ValueError(
                "Authentication body limit must be positive."
            )

        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope, receive, send) -> None:
        # Non-HTTP traffic must not be intercepted.
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "").upper()
        path = scope.get("path", "")

        if method != "POST" or path not in AUTH_WRITE_PATHS:
            await self.app(scope, receive, send)
            return

        body = bytearray()

        # Read the body through the public ASGI receive interface.
        # Reject as soon as the request exceeds the limit.
        while True:
            message = await receive()
            message_type = message.get("type")

            if message_type == "http.disconnect":
                # The client disconnected before completing the
                # request. Do not invoke the application handler.
                return

            if message_type != "http.request":
                continue

            chunk = message.get("body", b"")

            if len(body) + len(chunk) > self.max_body_bytes:
                response = JSONResponse(
                    {
                        "detail": (
                            "Authentication request is too large."
                        )
                    },
                    status_code=413,
                    headers={
                        "Cache-Control": "no-store",
                        "X-Content-Type-Options": "nosniff",
                    },
                )

                await response(scope, receive, send)
                return

            body.extend(chunk)

            if not message.get("more_body", False):
                break

        # The downstream application receives exactly the
        # validated body, using standard ASGI messages.
        replayed = False

        async def replay_receive():
            nonlocal replayed

            if not replayed:
                replayed = True

                return {
                    "type": "http.request",
                    "body": bytes(body),
                    "more_body": False,
                }

            # Once the body has been delivered, forward later
            # receive calls to the original channel. This also
            # preserves downstream disconnect notifications.
            return await receive()

        await self.app(scope, replay_receive, send)


class LoginRequest(BaseModel):
    """Constrain browser-submitted login fields."""

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=1024)


class RegistrationRequest(BaseModel):
    """Constrain browser-submitted registration fields."""

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=1024)


def create_app(
    *,
    secure_cookie: bool | None = None,
    api_client: FrontendAPIClient | None = None,
    allowed_origin: str | None = None,
) -> FastAPI:
    """
    Build the secured frontend ASGI application.

    Dependency injection is preserved for offline tests
    and compatibility with the existing authentication suite.
    """

    # ---------------------------------------------------------
    # 1. Configuration and security dependencies
    # ---------------------------------------------------------

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
        settings=HTTPSessionSettings(
            secure=secure_cookie
        ),
    )

    gate = GradioSecurityGate(cookies)
    gradio_auth = GradioAuthenticationAdapter(
        cookies=cookies,
        binding=binding,
    )
    gradio_sessions = TrustedGradioSessionIssuer(binding)
    gradio_authorizer = GradioExecutionAuthorizer(gradio_sessions)

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

    # Register the pure ASGI limiter.
    # It operates independently of FastAPI request parsing.
    application.add_middleware(
        AuthenticationBodyLimitMiddleware,
        max_body_bytes=MAX_AUTH_REQUEST_BYTES,
    )

    # ---------------------------------------------------------
    # 2. Shared security helpers
    # ---------------------------------------------------------

    def origin_denial(
        request: Request,
    ) -> JSONResponse | None:
        """
        Validate the trusted Origin for authentication writes.

        The trusted origin comes from explicit configuration,
        never an untrusted Host or Referer header.
        """

        try:
            guard = AuthenticationOriginGuard(
                allowed_origin=allowed_origin
            )
        except ValueError:
            return JSONResponse(
                {
                    "detail": (
                        "Frontend authentication "
                        "is not configured."
                    )
                },
                status_code=503,
            )

        try:
            guard.validate(request)
        except AuthenticationOriginError:
            return JSONResponse(
                {
                    "detail": (
                        "Request origin is not allowed."
                    )
                },
                status_code=403,
            )

        return None

    def browser_identity_denial(
        request: Request,
    ) -> tuple[str | None, JSONResponse | None]:
        """
        Read an existing registered browser identity.

        Unknown cookies are not accepted as identities.
        """

        identity = cookies.read_identity(request)

        if identity is None:
            return None, JSONResponse(
                {
                    "detail": "Browser session required."
                },
                status_code=401,
            )

        return identity, None

    # ---------------------------------------------------------
    # 3. HTTP security middleware
    # ---------------------------------------------------------

    @application.middleware("http")
    async def enforce_boundary(request: Request, call_next):
        """
        Preserve the existing restrictive Gradio gate.

        Add response security headers to authentication routes.

        Request-body limiting is handled separately by the
        supported ASGI middleware above.
        """

        # Gradio configuration is needed by the authenticated UI.
        # It is still read-only and requires server-side credentials.
        if (
            request.url.path == '/ui/config'
            and request.method in ('GET', 'HEAD')
        ):
            if gradio_auth(request) is None:
                return JSONResponse(
                    {'detail': 'Authentication required.'},
                    status_code=401,
                    headers={'Cache-Control': 'no-store'},
                )
            response = await call_next(request)
            response.headers['Cache-Control'] = 'no-store'
            return response

        denial = await gate.authorize(request)

        if denial is not None:
            return denial

        response = await call_next(request)

        if (
            request.url.path == "/auth"
            or request.url.path.startswith("/frontend-auth/")
        ):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = (
                "nosniff"
            )
            response.headers["Referrer-Policy"] = (
                "no-referrer"
            )
            response.headers["X-Frame-Options"] = "DENY"

        return response

    # ---------------------------------------------------------
    # 4. Browser bootstrap and authentication page
    # ---------------------------------------------------------

    @application.get(
        "/",
        include_in_schema=False,
    )
    def bootstrap(request: Request):
        """Create an anonymous browser identity if required."""

        identity = cookies.read_identity(request)

        response = RedirectResponse(
            "/auth",
            status_code=303,
        )

        if identity is None:
            identity = binding.create()
            cookies.set_identity(response, identity)

        return response

    @application.get(
        "/auth",
        include_in_schema=False,
        response_class=HTMLResponse,
    )
    def authentication_page(request: Request):
        """
        Render the authentication interface.

        Each response receives a fresh CSP nonce.
        """

        identity = cookies.read_identity(request)

        if identity is None:
            identity = binding.create()

        script_nonce = secrets.token_urlsafe(24)

        response = HTMLResponse(
            content=render_auth_page(
                script_nonce=script_nonce
            ),
            status_code=200,
        )

        cookies.set_identity(response, identity)

        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            "script-src 'nonce-" + script_nonce + "'; "
            "style-src 'unsafe-inline'; "
            "connect-src 'self'; "
            "form-action 'self'; "
            "base-uri 'none'; "
            "frame-ancestors 'none'"
        )

        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = (
            "nosniff"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"

        return response

    @application.get(
        "/healthz",
        include_in_schema=False,
    )
    def healthz():
        """Expose a minimal non-sensitive health check."""

        return {"status": "ok"}

    # ---------------------------------------------------------
    # 5. Authentication status
    # ---------------------------------------------------------

    @application.get(
        "/frontend-auth/status",
        include_in_schema=False,
    )
    def authentication_status(request: Request):
        """
        Report local frontend authentication status.

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
            {
                "authenticated": authenticated
            },
            headers={
                "Cache-Control": "no-store"
            },
        )

    # ---------------------------------------------------------
    # 6. Account registration
    # ---------------------------------------------------------

    @application.post(
        "/frontend-auth/register",
        include_in_schema=False,
    )
    def browser_register(
        request: Request,
        payload: RegistrationRequest,
    ):
        """
        Register through the existing FastAPI backend.

        Registration does not authenticate the browser,
        create frontend credentials, or issue JWTs.
        """

        denial = origin_denial(request)

        if denial is not None:
            return denial

        identity, identity_denial = browser_identity_denial(
            request
        )

        if identity_denial is not None:
            return identity_denial

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
            client.register(
                email=payload.email,
                password=payload.password,
            )

        except FrontendAPIError as error:
            if error.status_code == 409:
                return JSONResponse(
                    {
                        "detail": (
                            "Account could not be created "
                            "with these details."
                        )
                    },
                    status_code=409,
                )

            if error.status_code in {400, 422}:
                return JSONResponse(
                    {
                        "detail": (
                            "Invalid registration details."
                        )
                    },
                    status_code=422,
                )

            return JSONResponse(
                {
                    "detail": (
                        "Registration service temporarily "
                        "unavailable."
                    )
                },
                status_code=503,
            )

        return JSONResponse(
            {
                "registered": True,
                "authenticated": False,
            },
            status_code=201,
        )

    # ---------------------------------------------------------
    # 7. Login — preserve Phase 5.2.4 coordination
    # ---------------------------------------------------------

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

        Backend tokens never appear in the HTTP response.
        """

        denial = origin_denial(request)

        if denial is not None:
            return denial

        identity = cookies.read_identity(request)

        if identity is None:
            return JSONResponse(
                {
                    "detail": "Browser session required."
                },
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
            if error.status_code == 401:
                return JSONResponse(
                    {
                        "detail": (
                            "Authentication could not "
                            "be completed."
                        )
                    },
                    status_code=401,
                )

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
            {
                "authenticated": True
            },
            status_code=200,
            headers={
                "Cache-Control": "no-store"
            },
        )

        cookies.set_identity(
            response,
            replacement_identity,
        )

        return response

    # ---------------------------------------------------------
    # 8. Logout — preserve backend revocation behavior
    # ---------------------------------------------------------

    @application.post(
        "/frontend-auth/logout",
        include_in_schema=False,
    )
    def browser_logout(request: Request):
        """
        Attempt backend revocation and clear browser access.

        Remote revocation failures are not reported as
        confirmed successful logout.
        """

        denial = origin_denial(request)

        if denial is not None:
            return denial

        identity = cookies.read_identity(request)

        if identity is None:
            response = JSONResponse(
                {
                    "detail": "Browser session required."
                },
                status_code=401,
            )

            cookies.clear_identity(response)
            return response

        try:
            coordinator.logout(
                browser_identity=identity
            )

        except FrontendAPIError:
            response = JSONResponse(
                {
                    "detail": (
                        "Logout could not be confirmed."
                    )
                },
                status_code=503,
            )

        except Exception:
            # Unexpected errors must not leave the browser
            # attached to the old local identity.
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
                {
                    "authenticated": False
                },
                status_code=200,
            )

        gradio_sessions.revoke(identity)
        cookies.clear_identity(response)
        response.headers["Cache-Control"] = "no-store"

        return response

    # ---------------------------------------------------------
    # 8A. Server-issued Gradio session identifiers
    # ---------------------------------------------------------

    @application.post(
        "/frontend-gradio/session",
        include_in_schema=False,
    )
    def issue_gradio_session(request: Request):
        """Mint a browser-bound session hash; never accept one from input.

        This endpoint does not enable Gradio event or queue routes.
        """
        denial = origin_denial(request)
        if denial is not None:
            return denial

        identity = gradio_auth(request)
        if identity is None:
            return JSONResponse(
                {"detail": "Authentication required."},
                status_code=401,
                headers={"Cache-Control": "no-store"},
            )

        try:
            session_hash = gradio_sessions.issue(identity)
        except FrontendAPIError:
            return JSONResponse(
                {"detail": "Gradio session unavailable."},
                status_code=403,
                headers={"Cache-Control": "no-store"},
            )

        return JSONResponse(
            {"session_hash": session_hash},
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            },
        )

    # ---------------------------------------------------------
    # 8B. Secure, FastAPI-controlled execution boundary
    # ---------------------------------------------------------

    @application.post(
        "/frontend-gradio/execute",
        include_in_schema=False,
    )
    async def execute_protected_gradio_probe(request: Request):
        """Execute a minimal authenticated operation without Gradio's queue.

        This endpoint is deliberately separate from Gradio's client-generated
        session_hash and its callback/validator/cache machinery. The existing
        Gradio HTTP gate continues to deny every event and queue endpoint.
        """
        denial = origin_denial(request)
        if denial is not None:
            return denial

        identity = gradio_auth(request)
        if identity is None:
            return JSONResponse(
                {"detail": "Authentication required."},
                status_code=401,
                headers={"Cache-Control": "no-store"},
            )

        # Reject oversized bodies before JSON decoding; this endpoint has
        # a deliberately small and fixed request schema.
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            return JSONResponse(
                {"detail": "JSON request required."},
                status_code=415,
                headers={"Cache-Control": "no-store"},
            )
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 256:
                return JSONResponse(
                    {"detail": "Request too large."},
                    status_code=413,
                    headers={"Cache-Control": "no-store"},
                )
        try:
            import json
            body = json.loads(raw)
            if not isinstance(body, dict) or set(body) != {"session_hash"}:
                raise ValueError("Invalid request shape")
            session_hash = body["session_hash"]
            if not isinstance(session_hash, str) or len(session_hash) > 128:
                raise ValueError("Invalid session identifier")
        except (ValueError, TypeError, UnicodeDecodeError):
            return JSONResponse(
                {"detail": "Invalid request."},
                status_code=400,
                headers={"Cache-Control": "no-store"},
            )

        try:
            # Revalidate current ownership and server-side credentials
            # immediately before performing any protected operation.
            gradio_authorizer.authorize(identity, session_hash)
        except FrontendAPIError:
            return JSONResponse(
                {"detail": "Session not authorized."},
                status_code=403,
                headers={"Cache-Control": "no-store"},
            )

        return JSONResponse(
            {"verified": True},
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            },
        )

    # ---------------------------------------------------------
    # 9. Restricted Gradio shell
    # ---------------------------------------------------------

    # Gradio remains deliberately non-interactive.
    # Authenticated events will receive separate
    # authorization integration in Phase 5.2.6.
    with gr.Blocks(
        title="Health Advisor — Secure Frontend",
    ) as shell:
        gr.Markdown("# Health Risk & Cost Advisor")

        gr.Markdown(
            "Secure frontend initialized. "
            "Authentication is available at /auth. "
            "Protected policy operations are not enabled yet."
        )

    application = gr.mount_gradio_app(
        application,
        shell,
        path="/ui",
        auth_dependency=gradio_auth,
    )

    # ---------------------------------------------------------
    # 10. Trusted server-side dependency access
    # ---------------------------------------------------------

    # These objects are available to trusted tests and
    # server code, never serialized into browser responses.
    application.state.browser_binding = binding
    application.state.session_cookies = cookies
    application.state.auth_coordinator = coordinator
    application.state.gradio_auth = gradio_auth
    application.state.gradio_sessions = gradio_sessions
    application.state.gradio_authorizer = gradio_authorizer

    return application


app = create_app()