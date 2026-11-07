
"""
MODULE NAME
-----------
PHASE 5.2.6B PRODUCTION SERVER WIRING TESTS

PURPOSE
-------
Verify that the actual frontend FastAPI application
uses Gradio's authentication dependency.

DEPENDENCIES
------------
pytest, FastAPI TestClient, Gradio, and the existing
frontend application modules.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
- Production Gradio mount has an auth dependency.
- Anonymous browser cannot open protected Gradio.
- Authenticated browser can open Gradio.
- Configuration requires authentication.
- Logout invalidates access.
- Queue, event, and upload routes remain disabled.

ARCHITECTURE / DESIGN
---------------------
Uses the real create_app() factory with its in-memory
session registry. Authentication is established locally
using a SessionCredentialManager.

SECURITY CONSIDERATIONS
-----------------------
No backend tokens, real accounts, or external API calls
are used. These tests do not enable protected callbacks.

NOTES
-----
The tests validate production wiring, not backend
authorization or execution-time event authorization.
"""

from __future__ import annotations

import gradio as gr
import pytest

from fastapi.testclient import TestClient

from frontend.gradio_auth import GradioAuthenticationAdapter
from frontend.http_session import COOKIE_NAME
from frontend.server import create_app
from frontend.session_manager import SessionCredentialManager


@pytest.fixture
def environment():
    """Create a fresh real frontend application."""

    application = create_app(
        secure_cookie=False,
    )

    with TestClient(
        application,
        follow_redirects=False,
    ) as client:
        yield application, client

    application.state.browser_binding.close_all()


def authenticate(application, client):
    """
    Establish a local authenticated frontend session.

    No backend login is performed.
    """

    binding = application.state.browser_binding

    anonymous = binding.create()

    authenticated = binding.authenticate(
        anonymous,
        SessionCredentialManager(),
    )

    client.cookies.set(
        COOKIE_NAME,
        authenticated,
    )

    return authenticated


def test_production_mount_uses_auth_dependency(
    environment,
):
    """Gradio must have the production auth adapter."""

    application, _ = environment

    adapter = application.state.gradio_auth

    assert isinstance(
        adapter,
        GradioAuthenticationAdapter,
    )

    mounts = [
        route
        for route in application.routes
        if getattr(route, "path", None) == "/ui"
    ]

    assert len(mounts) == 1

    mount = mounts[0]

    assert isinstance(
        mount.app.blocks,
        gr.Blocks,
    )


def test_anonymous_browser_cannot_open_gradio(
    environment,
):
    """A registered anonymous cookie is insufficient."""

    application, client = environment

    anonymous = application.state.browser_binding.create()

    client.cookies.set(
        COOKIE_NAME,
        anonymous,
    )

    response = client.get("/ui/")

    assert response.status_code in {
        302, 303, 307, 401, 403
    }


def test_authenticated_browser_can_open_gradio(
    environment,
):
    """A locally authenticated browser can load Gradio."""

    application, client = environment

    authenticate(application, client)

    response = client.get("/ui/")

    assert response.status_code == 200


def test_anonymous_configuration_is_rejected(
    environment,
):
    """Gradio configuration must not be public."""

    application, client = environment

    anonymous = application.state.browser_binding.create()

    client.cookies.set(
        COOKIE_NAME,
        anonymous,
    )

    response = client.get("/ui/config")

    assert response.status_code in {401, 403}


def test_authenticated_configuration_is_available(
    environment,
):
    """Authenticated browsers can load UI configuration."""

    application, client = environment

    authenticate(application, client)

    response = client.get("/ui/config")

    assert response.status_code == 200

    configuration = response.json()

    assert isinstance(configuration, dict)
    assert "dependencies" in configuration


def test_logout_invalidates_gradio_access(
    environment,
):
    """Local session termination revokes UI access."""

    application, client = environment

    identity = authenticate(application, client)

    assert client.get("/ui/").status_code == 200

    application.state.browser_binding.terminate(identity)

    response = client.get("/ui/")

    assert response.status_code in {
        302, 303, 307, 401, 403
    }


@pytest.mark.parametrize(
    "path",
    [
        "/ui/gradio_api/queue/join",
        "/ui/gradio_api/run/predict",
        "/ui/gradio_api/upload",
        "/ui/file=private.pdf",
    ],
)
def test_protected_gradio_routes_remain_disabled(
    environment,
    path,
):
    """Authentication must not enable protected operations."""

    application, client = environment

    authenticate(application, client)

    response = client.post(path)

    assert response.status_code == 403