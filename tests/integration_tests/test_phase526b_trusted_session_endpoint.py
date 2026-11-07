"""
MODULE NAME
-----------
TRUSTED GRADIO SESSION ENDPOINT INTEGRATION TESTS

PURPOSE
-------
Verify production endpoint issues only server-minted session hashes.

DEPENDENCIES
------------
FastAPI TestClient, pytest, production frontend application.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
Origin enforcement, anonymous denial, successful authenticated
issuance, ignoring attacker-supplied hash, and cross-browser denial.

SECURITY NOTES
--------------
No real backend credentials, external requests, or paid services.
The Gradio event/queue gate must remain disabled.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from frontend.api_client import FrontendAPIError
from frontend.http_session import COOKIE_NAME
from frontend.server import create_app
from frontend.session_manager import SessionCredentialManager

ORIGIN = "http://testserver"


@pytest.fixture
def env():
    app = create_app(secure_cookie=False, allowed_origin=ORIGIN)
    with TestClient(app, follow_redirects=False) as client:
        yield app, client
    app.state.gradio_sessions.close_all()
    app.state.browser_binding.close_all()


def authenticated_identity(app, client):
    binding = app.state.browser_binding
    identity = binding.create(SessionCredentialManager())
    client.cookies.set(COOKIE_NAME, identity)
    return identity


def test_anonymous_issuance_denied(env):
    app, client = env
    client.cookies.set(COOKIE_NAME, app.state.browser_binding.create())
    response = client.post("/frontend-gradio/session", headers={"Origin": ORIGIN})
    assert response.status_code == 401


def test_missing_origin_denied(env):
    app, client = env
    authenticated_identity(app, client)
    response = client.post("/frontend-gradio/session")
    assert response.status_code == 403


def test_authenticated_issuance_is_server_generated(env):
    app, client = env
    identity = authenticated_identity(app, client)
    response = client.post(
        "/frontend-gradio/session",
        headers={"Origin": ORIGIN},
        json={"session_hash": "attacker-controlled"},
    )
    assert response.status_code == 200
    issued = response.json()["session_hash"]
    assert issued != "attacker-controlled"
    assert response.headers["cache-control"] == "no-store"
    assert app.state.gradio_sessions.verify(identity, issued) is app.state.browser_binding.resolve(identity)


def test_second_browser_cannot_verify_first_browser_hash(env):
    app, client = env
    first = authenticated_identity(app, client)
    response = client.post("/frontend-gradio/session", headers={"Origin": ORIGIN})
    assert response.status_code == 200
    issued = response.json()["session_hash"]
    second = app.state.browser_binding.create(SessionCredentialManager())
    with pytest.raises(FrontendAPIError):
        app.state.gradio_sessions.verify(second, issued)


def test_gradio_event_routes_remain_disabled(env):
    app, client = env
    authenticated_identity(app, client)
    response = client.post("/ui/gradio_api/queue/join")
    assert response.status_code == 403
