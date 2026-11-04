
"""
MODULE NAME
-----------
GRADIO HTTP SECURITY INTEGRATION TESTS

PURPOSE
-------
Verify the restricted frontend HTTP security boundary.

ENVIRONMENT / CONFIGURATION
---------------------------
Offline FastAPI TestClient execution.

No PostgreSQL, Gemini, external HTTP service, or
production credentials are required.

DEPENDENCIES
------------
pytest.
FastAPI TestClient.
Starlette.
frontend.server.
frontend.gradio_security.
frontend.http_session.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
- Browser cookie bootstrap.
- Secure cookie attributes.
- Cookie reuse.
- Missing and forged cookie rejection.
- Public Gradio shell accessibility.
- Gradio stylesheet authorization.
- Rejection of unknown endpoints.
- Rejection of unsafe HTTP methods.
- Rejection of queue, event, upload and file routes.
- Separation between independent browser clients.

SECURITY NOTES
--------------
These tests verify a restricted, non-interactive shell.

They do not establish authorization of enabled Gradio
events, queue results, or private documents.

Those capabilities remain disabled until later phases.
"""

from __future__ import annotations

import pytest

from fastapi.testclient import TestClient
from starlette.requests import Request

from frontend.gradio_security import GradioSecurityGate
from frontend.http_session import COOKIE_NAME
from frontend.server import create_app


@pytest.fixture
def client():
    """Create an isolated HTTP frontend test application."""

    application = create_app(secure_cookie=False)

    with TestClient(
        application,
        follow_redirects=False,
    ) as instance:
        yield instance


def bootstrap_browser(client: TestClient) -> None:
    """Establish a server-issued anonymous browser identity."""

    response = client.get("/")

    assert response.status_code == 303
    assert response.headers["location"] == "/ui/"


def test_bootstrap_issues_httponly_cookie(client):
    response = client.get("/")

    assert response.status_code == 303

    cookie = response.headers["set-cookie"].lower()

    assert COOKIE_NAME in cookie
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "path=/" in cookie


def test_cookie_is_reused_on_second_bootstrap(client):
    first = client.get("/")
    second = client.get("/")

    assert first.status_code == 303
    assert second.status_code == 303
    assert "set-cookie" not in second.headers


def test_no_cookie_cannot_access_gradio(client):
    client.cookies.clear()

    response = client.get("/ui/")

    assert response.status_code == 401


def test_forged_cookie_cannot_access_gradio(client):
    client.cookies.set(COOKIE_NAME, "forged")

    response = client.get("/ui/")

    assert response.status_code == 401


def test_authenticated_browser_can_access_shell(client):
    bootstrap_browser(client)

    response = client.get("/ui/")

    assert response.status_code == 200
    assert "Health Risk" in response.text


def test_theme_css_is_not_blocked_by_security_gate(client):
    """
    The stylesheet must pass the gate.

    The underlying Gradio route may return its own
    response, but the gate must not return 401 or 403.
    """

    bootstrap_browser(client)

    response = client.get("/ui/theme.css?v=test")

    assert response.status_code not in (401, 403)


def test_theme_css_requires_browser_cookie(client):
    client.cookies.clear()

    response = client.get("/ui/theme.css")

    assert response.status_code == 401


@pytest.mark.parametrize(
    "path,method",
    [
        ("/ui/gradio_api/queue/join", "POST"),
        (
            "/ui/gradio_api/queue/data?session_hash=stolen",
            "GET",
        ),
        ("/ui/gradio_api/run/predict", "POST"),
        ("/ui/gradio_api/call/predict", "POST"),
        ("/ui/gradio_api/upload", "POST"),
        ("/ui/gradio_api/file=private.pdf", "GET"),
        ("/ui/gradio_api/heartbeat/stolen", "GET"),
        ("/ui/gradio_api/reset", "POST"),
        ("/ui/gradio_api/config", "GET"),
        ("/ui/gradio_api/info", "GET"),
        ("/ui/gradio_api/openapi.json", "GET"),
        ("/ui/file=private.pdf", "GET"),
        ("/ui/reset", "POST"),
    ],
)
def test_protected_gradio_routes_fail_closed(
    client,
    path,
    method,
):
    bootstrap_browser(client)

    response = client.request(method, path)

    assert response.status_code == 403


@pytest.mark.parametrize(
    "path",
    [
        "/ui/unknown",
        "/ui/private",
        "/ui/config",
        "/ui/theme.css/private",
        "/ui/gradio_api/",
        "/ui/assets/",
    ],
)
def test_unknown_routes_fail_closed(client, path):
    bootstrap_browser(client)

    response = client.get(path)

    assert response.status_code == 403


@pytest.mark.parametrize(
    "method",
    ["POST", "PUT", "PATCH", "DELETE"],
)
def test_unsafe_methods_are_blocked_on_shell(client, method):
    bootstrap_browser(client)

    response = client.request(method, "/ui/")

    assert response.status_code == 403


def test_healthcheck_is_public(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_two_browser_clients_receive_different_cookies():
    """
    Independent clients must not share browser identities.
    """

    application = create_app(secure_cookie=False)

    with (
        TestClient(
            application,
            follow_redirects=False,
        ) as first_client,
        TestClient(
            application,
            follow_redirects=False,
        ) as second_client,
    ):
        bootstrap_browser(first_client)
        bootstrap_browser(second_client)

        first_cookie = first_client.cookies.get(COOKIE_NAME)
        second_cookie = second_client.cookies.get(COOKIE_NAME)

        assert first_cookie
        assert second_cookie
        assert first_cookie != second_cookie

        assert first_client.get("/ui/").status_code == 200
        assert second_client.get("/ui/").status_code == 200


def test_unrecognized_mount_path_is_not_authorized():
    """
    The gate must not accidentally authorize a different
    application namespace.
    """

    application = create_app(secure_cookie=False)
    gate = GradioSecurityGate(
        application.state.session_cookies
    )

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/other-app/",
            "headers": [],
            "query_string": b"",
        }
    )

    assert gate._is_gradio_path(request.url.path) is False


def test_invalid_mount_path_is_rejected():
    application = create_app(secure_cookie=False)
    cookies = application.state.session_cookies

    with pytest.raises(ValueError):
        GradioSecurityGate(cookies, mount_path="/")

    with pytest.raises(ValueError):
        GradioSecurityGate(cookies, mount_path="ui")


def test_asset_path_validation_rejects_suspicious_paths():
    """
    Verify the gate's allowlist logic without relying
    on the HTTP client's URL normalization.
    """

    application = create_app(secure_cookie=False)
    gate = GradioSecurityGate(
        application.state.session_cookies
    )

    assert gate._is_allowed_public_resource(
        "/ui/assets/main.js"
    )

    assert not gate._is_allowed_public_resource(
        "/ui/assets/"
    )

    assert not gate._is_allowed_public_resource(
        "/ui/assets/../private"
    )

    assert not gate._is_allowed_public_resource(
        "/ui/assets//private"
    )

def test_public_gradio_font_is_accessible(client):
    """Bundled Gradio fonts must load for a valid browser."""

    bootstrap_browser(client)

    response = client.get(
        "/ui/static/fonts/SourceSansPro/"
        "SourceSansPro-SemiBold.woff2"
    )

    assert response.status_code == 200


def test_unapproved_static_resource_is_blocked(client):
    """Other static paths must remain inaccessible."""

    bootstrap_browser(client)

    response = client.get(
        "/ui/static/private-document.pdf"
    )

    assert response.status_code == 403