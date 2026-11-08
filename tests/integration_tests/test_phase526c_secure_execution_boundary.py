"""
MODULE NAME
-----------
PHASE 5.2.6C SECURE EXECUTION BOUNDARY TESTS

PURPOSE
-------
Exercise the real FastAPI admission boundary without exposing Gradio's
client-generated session hash, queue, validator, cache, upload or file paths.

ENVIRONMENT / CONFIGURATION
---------------------------
Local TestClient only. No paid APIs, database, or remote backend.

DEPENDENCIES
------------
pytest, FastAPI TestClient, existing frontend application.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
Origin, cookie, trusted hash, cross-browser, logout/expiry and closed Gradio gate.

SECURITY CONSIDERATIONS
-----------------------
The successful probe uses a mocked authorizer because it tests HTTP wiring;
separate unit tests exercise the real authorizer and credential manager.

NOTES
-----
This is a secure FastAPI-controlled operation, NOT an enabled Gradio queue.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from frontend.api_client import FrontendAPIError
from frontend.gradio_execution_authorizer import GradioExecutionAuthorizer
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


def authenticate(app, client):
    identity = app.state.browser_binding.create(SessionCredentialManager())
    client.cookies.set(COOKIE_NAME, identity)
    return identity


def issue(app, identity):
    return app.state.gradio_sessions.issue(identity)


def post(client, session_hash, *, origin=ORIGIN):
    headers = {"Origin": origin} if origin is not None else {}
    return client.post(
        "/frontend-gradio/execute",
        json={"session_hash": session_hash},
        headers=headers,
    )


def test_anonymous_denied(env):
    app, client = env
    client.cookies.set(COOKIE_NAME, app.state.browser_binding.create())
    assert post(client, "forged").status_code == 401


def test_origin_required(env):
    app, client = env
    identity = authenticate(app, client)
    assert post(client, issue(app, identity), origin=None).status_code == 403


def test_forged_hash_denied(env):
    app, client = env
    authenticate(app, client)
    assert post(client, "forged").status_code == 403


def test_cross_browser_hash_denied(env):
    app, client = env
    first = authenticate(app, client)
    issued = issue(app, first)
    authenticate(app, client)
    assert post(client, issued).status_code == 403


def test_revoked_hash_denied(env):
    app, client = env
    identity = authenticate(app, client)
    issued = issue(app, identity)
    app.state.gradio_sessions.revoke(identity)
    assert post(client, issued).status_code == 403


def test_valid_request_invokes_authorizer_without_exposing_token(env):
    app, client = env
    identity = authenticate(app, client)
    issued = issue(app, identity)
    with patch.object(
        GradioExecutionAuthorizer,
        "authorize",
        return_value=SimpleNamespace(access_token="private-token"),
    ) as authorize:
        response = post(client, issued)
    assert response.status_code == 200
    assert response.json() == {"verified": True}
    assert "private-token" not in response.text
    authorize.assert_called_once_with(identity, issued)


def test_rejected_authorization_denies(env):
    app, client = env
    identity = authenticate(app, client)
    issued = issue(app, identity)
    with patch.object(
        GradioExecutionAuthorizer,
        "authorize",
        side_effect=FrontendAPIError("expired"),
    ):
        assert post(client, issued).status_code == 403


def test_gradio_queue_remains_closed(env):
    app, client = env
    identity = authenticate(app, client)
    issued = issue(app, identity)
    assert client.post(
        "/ui/gradio_api/queue/join",
        json={"session_hash": issued},
        headers={"Origin": ORIGIN},
    ).status_code == 403


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/ui/queue/join"),
        ("POST", "/ui/call/v2/verify_session"),
        ("POST", "/ui/call/verify_session"),
        ("GET", "/ui/queue/data?session_hash=forged"),
    ],
)
def test_anonymous_native_gradio_routes_are_blocked(env, method, path):
    """
    Verify that anonymous requests cannot access native Gradio
    event submission or queue-result endpoints.

    This is a default-deny regression test, not proof that
    authenticated native Gradio execution is safe.
    """
    _app, client = env

    # Explicitly ensure the browser has no authentication cookie.
    client.cookies.clear()

    response = client.request(method, path)

    assert response.status_code == 401, (
        f"Anonymous Gradio route was not rejected: "
        f"{method} {path} returned {response.status_code}"
    )