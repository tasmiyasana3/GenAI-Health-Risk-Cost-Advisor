
"""
MODULE NAME
-----------
PHASE 5.2.6B GRADIO AUTHENTICATION CONTRACT TESTS

PURPOSE
-------
Verify the supported authentication integration between
FastAPI and Gradio before enabling protected application
callbacks.

These tests use an isolated Gradio application. They do
not modify the production frontend or its security gate.

ENVIRONMENT / CONFIGURATION
---------------------------
Python 3.13.
Gradio 6.30.0.
FastAPI and Starlette TestClient.

All tests run locally without PostgreSQL, Gemini,
external HTTP requests, or paid services.

DEPENDENCIES
------------
pytest.
gradio.
fastapi.
starlette.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
- Verify the installed Gradio version.
- Verify that auth_dependency is supported.
- Construct an isolated mounted Gradio application.
- Verify authenticated access to the Gradio page.
- Verify rejection of anonymous page access.
- Verify that the dependency receives the HTTP request.
- Verify authentication for Gradio configuration access.
- Verify that a callback is registered.
- Verify the supported Gradio request interface.

ARCHITECTURE / DESIGN
---------------------
The test application uses a fictional authentication
dependency and a harmless callback.

A test-only cookie simulates authenticated identity.
It is not a production session credential.

Production authentication must continue to use the
existing BrowserSessionBinding and backend credentials.

SECURITY CONSIDERATIONS
-----------------------
The test cookie is intentionally not a production
authentication mechanism.

These tests do not establish ownership of a Gradio
session_hash or execution-time queue authorization.

Those properties require separate security tests
before protected events can be enabled.

NOTES
-----
Keep this contract test independent of the existing
production frontend.

Do not use this test's simplified authentication
dependency in production.
"""

from __future__ import annotations

import inspect

import gradio as gr
import pytest

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.routing import Mount


TEST_COOKIE_NAME = "phase526b_test_identity"
TEST_IDENTITY = "fictional-authenticated-user"


def test_auth_dependency_interface_is_supported() -> None:
    """
    Confirm that the installed Gradio version exposes
    the authentication integration we intend to use.
    """

    assert gr.__version__ == "6.30.0"

    signature = inspect.signature(gr.mount_gradio_app)

    assert "auth_dependency" in signature.parameters


def test_gradio_request_supports_session_context() -> None:
    """
    Verify that Gradio exposes the documented request
    context required by future callback authorization.
    """

    signature = inspect.signature(gr.Request)

    assert "request" in signature.parameters
    assert "username" in signature.parameters
    assert "session_hash" in signature.parameters


@pytest.fixture
def isolated_gradio_app():
    """
    Construct a separate application for contract tests.

    The callback is deliberately harmless and does not
    access insurance data or backend services.
    """

    application = FastAPI()

    dependency_calls: list[str | None] = []

    def authenticate_request(
        request: Request,
    ) -> str | None:
        """
        Simulate authentication using a fictional cookie.

        This is a test double, not production auth.
        """

        identity = request.cookies.get(TEST_COOKIE_NAME)

        dependency_calls.append(identity)

        if identity == TEST_IDENTITY:
            return identity

        return None

    def harmless_callback(value: str) -> str:
        """
        A registered event used only for framework
        compatibility inspection.
        """

        return f"Received: {value}"

    with gr.Blocks(
        title="Phase 5.2.6B Contract Test",
    ) as interface:
        gr.Markdown("Authentication contract test")

        value = gr.Textbox(label="Test input")

        output = gr.Textbox(label="Test output")

        button = gr.Button("Test callback")

        button.click(
            fn=harmless_callback,
            inputs=value,
            outputs=output,
            api_name="phase526b_test_callback",
            api_visibility="private",
            queue=False,
        )

    mounted_application = gr.mount_gradio_app(
        application,
        interface,
        path="/ui",
        auth_dependency=authenticate_request,
        show_error=False,
    )

    return mounted_application, dependency_calls


@pytest.fixture
def contract_client(isolated_gradio_app):
    """Provide an isolated local HTTP client."""

    application, dependency_calls = isolated_gradio_app

    with TestClient(
        application,
        follow_redirects=False,
    ) as client:
        yield client, dependency_calls


def test_gradio_is_mounted(
    isolated_gradio_app,
) -> None:
    """Verify that the isolated application has a mount."""

    application, _ = isolated_gradio_app

    mounts = [
        route
        for route in application.routes
        if isinstance(route, Mount)
    ]

    assert any(route.path == "/ui" for route in mounts)


def test_anonymous_page_access_is_rejected(
    contract_client,
) -> None:
    """
    Verify that a browser without the fictional
    authenticated identity cannot open the UI.
    """

    client, dependency_calls = contract_client

    response = client.get("/ui/")

    assert response.status_code in {
        302,
        303,
        307,
        401,
        403,
    }

    assert dependency_calls


def test_authenticated_page_access_is_allowed(
    contract_client,
) -> None:
    """Verify that the authentication hook accepts a user."""

    client, dependency_calls = contract_client

    client.cookies.set(
        TEST_COOKIE_NAME,
        TEST_IDENTITY,
    )

    response = client.get("/ui/")

    assert response.status_code == 200

    assert TEST_IDENTITY in dependency_calls


def test_anonymous_configuration_is_rejected(
    contract_client,
) -> None:
    """
    Verify that Gradio configuration cannot be read
    anonymously when auth_dependency is configured.
    """

    client, dependency_calls = contract_client

    response = client.get("/ui/config")

    assert response.status_code in {
        302,
        303,
        307,
        401,
        403,
    }

    assert dependency_calls


def test_authenticated_configuration_is_available(
    contract_client,
) -> None:
    """
    Verify that the authenticated browser can retrieve
    the Gradio application configuration.
    """

    client, dependency_calls = contract_client

    client.cookies.set(
        TEST_COOKIE_NAME,
        TEST_IDENTITY,
    )

    response = client.get("/ui/config")

    assert response.status_code == 200

    configuration = response.json()

    assert isinstance(configuration, dict)

    assert "dependencies" in configuration

    assert TEST_IDENTITY in dependency_calls


def test_callback_is_registered(
    isolated_gradio_app,
) -> None:
    """
    Verify that the isolated application actually has
    an event dependency.

    This does not execute the callback.
    """

    application, _ = isolated_gradio_app

    gradio_mount = next(
        route
        for route in application.routes
        if isinstance(route, Mount)
        and route.path == "/ui"
    )

    blocks = getattr(
        gradio_mount.app,
        "blocks",
        None,
    )

    assert blocks is not None

    configuration = blocks.get_config_file()

    dependencies = configuration.get(
        "dependencies",
        [],
    )

    assert dependencies

    assert any(
        dependency.get("api_name")
        == "phase526b_test_callback"
        for dependency in dependencies
    )


def test_no_production_services_are_required(
    isolated_gradio_app,
) -> None:
    """
    Confirm the contract fixture exposes only the
    isolated application and its call recorder.

    This test does not instantiate backend clients,
    credential managers, or application databases.
    """

    application, dependency_calls = isolated_gradio_app

    assert isinstance(application, FastAPI)
    assert isinstance(dependency_calls, list)