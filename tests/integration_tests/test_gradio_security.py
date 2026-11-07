
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
- Authentication-page landing redirect.
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
These tests verify the browser identity boundary
and the restricted, non-interactive Gradio shell.

A browser identity cookie is not proof of a
successfully authenticated user account.

These tests do not establish authorization of enabled
Gradio events, queue results, or private documents.

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
    """
    Establish a server-issued anonymous browser identity.

    Phase 5.2.5B changed the landing destination
    from /ui/ to /auth.

    This helper checks browser bootstrap only.
    It does not perform account authentication.
    """

    response = client.get("/")

    assert response.status_code == 303
    assert response.headers["location"] == "/auth"


def test_root_redirects_to_authentication_page(client):
    """
    Verify that the application starts at the
    authentication entry point.
    """

    response = client.get("/")

    assert response.status_code == 303
    assert response.headers["location"] == "/auth"


def test_bootstrap_issues_httponly_cookie(client):
    """Verify browser identity cookie security attributes."""

    response = client.get("/")

    assert response.status_code == 303

    cookie = response.headers["set-cookie"].lower()

    assert COOKIE_NAME in cookie
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "path=/" in cookie


def test_cookie_is_reused_on_second_bootstrap(client):
    """Existing valid browser identity must be reused."""

    first = client.get("/")
    second = client.get("/")

    assert first.status_code == 303
    assert second.status_code == 303
    assert "set-cookie" not in second.headers


def test_no_cookie_cannot_access_gradio(client):
    """Reject requests without a browser identity cookie."""

    client.cookies.clear()

    response = client.get("/ui/")

    assert response.status_code == 401


def test_forged_cookie_cannot_access_gradio(client):
    """Reject forged browser identity cookies."""

    client.cookies.set(COOKIE_NAME, "forged")

    response = client.get("/ui/")

    assert response.status_code == 401



def test_anonymous_browser_cannot_access_protected_shell(client):
    """
    A registered browser identity is not sufficient
    to access the authenticated Gradio application.

    This replaces the Phase 5.2.5B anonymous-shell
    expectation following Phase 5.2.6B wiring.
    """

    bootstrap_browser(client)

    response = client.get("/ui/")

    assert response.status_code in {
        302, 303, 307, 401, 403
    }


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
    """A browser without identity cannot request the theme."""

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
    """
    Browser identity must never authorize
    protected Gradio operations.
    """

    bootstrap_browser(client)

    response = client.request(method, path)

    assert response.status_code == 403


@pytest.mark.parametrize(
    "path",
    [
        "/ui/unknown",
        "/ui/private",
        "/ui/theme.css/private",
        "/ui/gradio_api/",
        "/ui/assets/",
    ],
)
def test_unknown_routes_fail_closed(client, path):
    """Unknown and unapproved Gradio paths are denied."""

    bootstrap_browser(client)

    response = client.get(path)

    assert response.status_code == 403


def test_gradio_config_rejects_anonymous_browser(client):
    """
    A registered anonymous browser must not access
    the protected Gradio configuration endpoint.
    """
    bootstrap_browser(client)

    response = client.get("/ui/config")

    assert response.status_code == 401


@pytest.mark.parametrize(
    "method",
    ["POST", "PUT", "PATCH", "DELETE"],
)
def test_unsafe_methods_are_blocked_on_shell(client, method):
    """The restricted shell must reject unsafe methods."""

    bootstrap_browser(client)

    response = client.request(method, "/ui/")

    assert response.status_code == 403


def test_healthcheck_is_public(client):
    """Health checks must not require browser authentication."""

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_two_browser_clients_receive_different_cookies():
    """
    Independent browser clients must receive
    independent server-issued browser identities.
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

        # Both browsers have cookies but are not logged in.
        # Neither may access the protected Gradio interface.
        assert first_client.get("/ui/").status_code == 401
        assert second_client.get("/ui/").status_code == 401


def test_unrecognized_mount_path_is_not_authorized():
    """
    The gate must not accidentally authorize
    another application namespace.
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
    """Reject invalid security-gate mount configuration."""

    application = create_app(secure_cookie=False)
    cookies = application.state.session_cookies

    with pytest.raises(ValueError):
        GradioSecurityGate(cookies, mount_path="/")

    with pytest.raises(ValueError):
        GradioSecurityGate(cookies, mount_path="ui")


def test_asset_path_validation_rejects_suspicious_paths():
    """
    Verify the gate's allowlist logic without
    relying on HTTP client URL normalization.
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
    """Unapproved static resources must remain inaccessible."""

    bootstrap_browser(client)

    response = client.get(
        "/ui/static/private-document.pdf"
    )

    assert response.status_code == 403