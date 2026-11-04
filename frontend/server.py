
"""MODULE NAME: SECURED FRONTEND ASGI ENTRY POINT

PURPOSE
-------
Serve a non-interactive Gradio shell behind server-issued browser cookies.

ENVIRONMENT / CONFIGURATION
---------------------------
FRONTEND_COOKIE_SECURE=true (required for HTTPS production).
FRONTEND_COOKIE_SECURE=false is permitted only for local HTTP testing.
Launch with uvicorn frontend.server:app --workers 1.

DEPENDENCIES
------------
FastAPI, Gradio, frontend browser binding and cookie utilities.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
Bootstrap anonymous browser sessions, protect mounted Gradio paths,
keep existing direct-service callbacks out of the public server.

SECURITY NOTES
--------------
This intentionally disables Gradio API/events/files. It does not provide
an authenticated interactive application. Never mount the legacy dashboard
here before API-backed callbacks and resource authorization are complete.
"""
from __future__ import annotations

import os

import gradio as gr
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

from frontend.browser_session_binding import BrowserSessionBinding
from frontend.gradio_security import GradioSecurityGate
from frontend.http_session import (
    HTTPSessionCookies,
    HTTPSessionSettings,
)
from frontend.session_binding import SessionRegistry


def create_app(*, secure_cookie: bool | None = None) -> FastAPI:
    """Build a single-process frontend without importing legacy callbacks."""

    if secure_cookie is None:
        setting = os.getenv(
            "FRONTEND_COOKIE_SECURE",
            "true",
        ).strip().lower()

        if setting not in ("true", "false"):
            raise ValueError(
                "FRONTEND_COOKIE_SECURE must be true or false."
            )

        secure_cookie = setting == "true"

    registry = SessionRegistry()
    binding = BrowserSessionBinding(registry)

    cookies = HTTPSessionCookies(
        binding,
        settings=HTTPSessionSettings(
            secure=secure_cookie,
        ),
    )

    gate = GradioSecurityGate(cookies)

    application = FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @application.middleware("http")
    async def enforce_boundary(request: Request, call_next):
        denial = await gate.authorize(request)

        if denial is not None:
            return denial

        return await call_next(request)

    @application.get("/", include_in_schema=False)
    def bootstrap(request: Request):
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
        return {"status": "ok"}

    # This shell deliberately has no callbacks,
    # upload inputs or secrets.
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

    application.state.browser_binding = binding
    application.state.session_cookies = cookies

    return application


app = create_app()