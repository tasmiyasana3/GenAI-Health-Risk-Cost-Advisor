
"""
MODULE NAME
-----------
PHASE 5.2.6B SESSION AUTHENTICATION INTEGRATION TESTS

PURPOSE
-------
Verify that the production Gradio authentication adapter
works with real frontend browser-session components and
Gradio's supported authentication dependency.

RESPONSIBILITIES
----------------
- Reject requests without a registered browser cookie.
- Reject registered but anonymous browser identities.
- Accept server-authenticated browser identities.
- Reject identities invalidated by login rotation.
- Reject terminated browser sessions.
- Preserve isolation between independent browsers.
- Keep credential-manager objects out of HTTP responses.

ARCHITECTURE / DESIGN
---------------------
An isolated FastAPI application mounts a minimal Gradio
interface using the production authentication adapter.

The test uses real in-memory frontend session components.
It does not use the production application's HTTP routes.

No backend login is performed. SessionCredentialManager
instances are created locally to represent successful
authentication after the backend has verified a user.

SECURITY CONSIDERATIONS
-----------------------
- No real passwords, JWTs, or refresh tokens are used.
- No Gemini or external HTTP requests are performed.
- The test does not authorize arbitrary session_hash values.
- It does not establish queue execution-time authorization.
- The production GradioSecurityGate remains unchanged.

NOTES
-----
These tests exercise framework integration and browser
authentication lifecycle, not protected event execution.

Run using pytest from the repository root.
"""

from __future__ import annotations

from dataclasses import dataclass

import gradio as gr
import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from frontend.browser_session_binding import BrowserSessionBinding
from frontend.gradio_auth import GradioAuthenticationAdapter
from frontend.http_session import (
    COOKIE_NAME,
    HTTPSessionCookies,
    HTTPSessionSettings,
)
from frontend.session_binding import SessionRegistry
from frontend.session_manager import SessionCredentialManager


DENIAL_STATUSES = {302, 303, 307, 401, 403}


@dataclass
class IntegrationEnvironment:
    """Hold the real frontend components used in each test."""

    client: TestClient
    binding: BrowserSessionBinding
    cookies: HTTPSessionCookies

    def authenticate_browser(self) -> str:
        """
        Simulate the state after successful backend login.

        This method does not call the backend. It uses the
        existing credential manager and binding APIs.
        """

        anonymous_identity = self.binding.create()

        manager = SessionCredentialManager()

        return self.binding.authenticate(
            anonymous_identity,
            manager,
        )

    def set_browser_cookie(self, identity: str) -> None:
        """Set a browser cookie for the local HTTP client."""

        self.client.cookies.set(
            COOKIE_NAME,
            identity,
        )


@pytest.fixture
def environment():
    """
    Construct a separate Gradio application using real
    production authentication and session components.
    """

    registry = SessionRegistry()
    binding = BrowserSessionBinding(registry)

    cookies = HTTPSessionCookies(
        binding,
        settings=HTTPSessionSettings(
            secure=False,
        ),
    )

    adapter = GradioAuthenticationAdapter(
        cookies=cookies,
        binding=binding,
    )

    application = FastAPI()

    with gr.Blocks(
        title="Session Authentication Integration",
    ) as interface:
        gr.Markdown("Authenticated integration test")

    application = gr.mount_gradio_app(
        application,
        interface,
        path="/ui",
        auth_dependency=adapter,
        show_error=False,
    )

    with TestClient(
        application,
        follow_redirects=False,
    ) as client:
        yield IntegrationEnvironment(
            client=client,
            binding=binding,
            cookies=cookies,
        )

    binding.close_all()


def test_missing_browser_cookie_is_rejected(
    environment: IntegrationEnvironment,
) -> None:
    """A browser without an identity must not enter Gradio."""

    response = environment.client.get("/ui/")

    assert response.status_code in DENIAL_STATUSES


def test_unknown_browser_cookie_is_rejected(
    environment: IntegrationEnvironment,
) -> None:
    """A fabricated cookie must not authenticate a browser."""

    environment.set_browser_cookie(
        "fictional-unknown-browser"
    )

    response = environment.client.get("/ui/")

    assert response.status_code in DENIAL_STATUSES


def test_registered_anonymous_browser_is_rejected(
    environment: IntegrationEnvironment,
) -> None:
    """
    A valid browser cookie is insufficient without
    authenticated server-side credentials.
    """

    identity = environment.binding.create()

    environment.set_browser_cookie(identity)

    response = environment.client.get("/ui/")

    assert response.status_code in DENIAL_STATUSES


def test_authenticated_browser_can_open_gradio(
    environment: IntegrationEnvironment,
) -> None:
    """A server-authenticated browser may open the UI."""

    identity = environment.authenticate_browser()

    environment.set_browser_cookie(identity)

    response = environment.client.get("/ui/")

    assert response.status_code == 200


def test_login_rotation_invalidates_previous_identity(
    environment: IntegrationEnvironment,
) -> None:
    """
    A browser identity that existed before login must
    not remain valid after authentication rotates it.
    """

    old_identity = environment.binding.create()

    new_identity = environment.binding.authenticate(
        old_identity,
        SessionCredentialManager(),
    )

    environment.set_browser_cookie(old_identity)

    old_response = environment.client.get("/ui/")

    assert old_response.status_code in DENIAL_STATUSES

    environment.set_browser_cookie(new_identity)

    new_response = environment.client.get("/ui/")

    assert new_response.status_code == 200


def test_terminated_browser_cannot_access_gradio(
    environment: IntegrationEnvironment,
) -> None:
    """Logout must invalidate the browser's local identity."""

    identity = environment.authenticate_browser()

    environment.set_browser_cookie(identity)

    before_logout = environment.client.get("/ui/")

    assert before_logout.status_code == 200

    environment.binding.terminate(identity)

    after_logout = environment.client.get("/ui/")

    assert after_logout.status_code in DENIAL_STATUSES


def test_independent_browser_sessions_remain_isolated(
    environment: IntegrationEnvironment,
) -> None:
    """
    Terminating one browser must not invalidate another
    independently authenticated browser.
    """

    first_identity = environment.authenticate_browser()
    second_identity = environment.authenticate_browser()

    environment.set_browser_cookie(first_identity)

    first_response = environment.client.get("/ui/")

    assert first_response.status_code == 200

    environment.binding.terminate(first_identity)

    environment.set_browser_cookie(second_identity)

    second_response = environment.client.get("/ui/")

    assert second_response.status_code == 200


def test_gradio_configuration_requires_authentication(
    environment: IntegrationEnvironment,
) -> None:
    """
    Verify authentication behavior for the mounted
    Gradio configuration endpoint.
    """

    anonymous_response = environment.client.get(
        "/ui/config"
    )

    assert anonymous_response.status_code in DENIAL_STATUSES

    identity = environment.authenticate_browser()

    environment.set_browser_cookie(identity)

    authenticated_response = environment.client.get(
        "/ui/config"
    )

    assert authenticated_response.status_code == 200

    configuration = authenticated_response.json()

    assert isinstance(configuration, dict)
    assert "dependencies" in configuration