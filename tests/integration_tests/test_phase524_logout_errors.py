
"""
MODULE NAME
-----------
PHASE 5.2.4 LOGOUT AND ERROR CLASSIFICATION TESTS

PURPOSE
-------
Verify browser logout, cookie invalidation, origin protection,
and correct classification of backend login failures.

ENVIRONMENT / CONFIGURATION
---------------------------
Offline pytest with FastAPI TestClient.
No running backend, database, Gemini, or paid API.

DEPENDENCIES
------------
pytest, FastAPI TestClient, and existing frontend modules.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
- Successful logout revokes backend credentials.
- Logout invalidates the browser cookie.
- Failed backend logout still removes local browser access.
- Backend outages return 503 rather than 401.
- Invalid passwords return 401.
- Logout requires a trusted Origin.
- Logout cannot affect another browser session.
- Missing cookies cannot initiate backend logout.

SECURITY NOTES
--------------
All tokens and passwords are synthetic.
Backend revocation failure is not reported as success.
"""

from __future__ import annotations

import pytest

from fastapi.testclient import TestClient

from frontend.api_client import (
    AuthenticationCredentials,
    FrontendAPIError,
)
from frontend.http_session import COOKIE_NAME
from frontend.server import create_app


ORIGIN = "http://127.0.0.1:7860"


class FakeBackend:
    """Simulate authentication and controllable backend failures."""

    def __init__(self) -> None:
        self.login_status: int | None = None
        self.fail_logout = False
        self.counter = 0
        self.revoked: list[str] = []

    def login(self, email, password):
        if self.login_status is not None:
            raise FrontendAPIError(
                "Synthetic backend failure.",
                status_code=self.login_status,
            )

        self.counter += 1

        return AuthenticationCredentials(
            access_token=f"access-{self.counter}",
            refresh_token=f"refresh-{self.counter}",
            expires_in=1800,
        )

    def refresh(self, refresh_token):
        raise AssertionError("Unexpected refresh.")

    def logout(self, refresh_token):
        if self.fail_logout:
            raise FrontendAPIError(
                "Synthetic logout failure.",
                status_code=503,
            )

        self.revoked.append(refresh_token)


@pytest.fixture
def environment():
    backend = FakeBackend()

    app = create_app(
        secure_cookie=False,
        api_client=backend,
        allowed_origin=ORIGIN,
    )

    with TestClient(
        app,
        follow_redirects=False,
    ) as browser:
        yield browser, app, backend

    app.state.browser_binding.close_all()


def bootstrap(browser):
    response = browser.get("/")
    assert response.status_code == 303
    assert browser.cookies.get(COOKIE_NAME)


def login(browser):
    return browser.post(
        "/frontend-auth/login",
        headers={"Origin": ORIGIN},
        json={
            "email": "test@example.test",
            "password": "synthetic-password",
        },
    )


def logout(browser, *, origin=ORIGIN):
    headers = (
        {"Origin": origin}
        if origin is not None
        else {}
    )

    return browser.post(
        "/frontend-auth/logout",
        headers=headers,
    )


def test_successful_logout_revokes_backend_session(environment):
    browser, _, backend = environment

    bootstrap(browser)
    assert login(browser).status_code == 200

    response = logout(browser)

    assert response.status_code == 200
    assert response.json() == {"authenticated": False}
    assert backend.revoked == ["refresh-1"]
    assert browser.cookies.get(COOKIE_NAME) is None


def test_logout_invalidates_previous_identity(environment):
    browser, app, _ = environment

    bootstrap(browser)
    assert login(browser).status_code == 200

    old_identity = browser.cookies.get(COOKIE_NAME)

    assert logout(browser).status_code == 200

    assert not app.state.browser_binding.exists(
        old_identity
    )


def test_failed_backend_logout_clears_local_access(environment):
    browser, app, backend = environment

    bootstrap(browser)
    assert login(browser).status_code == 200

    identity = browser.cookies.get(COOKIE_NAME)
    backend.fail_logout = True

    response = logout(browser)

    assert response.status_code == 503
    assert browser.cookies.get(COOKIE_NAME) is None
    assert not app.state.browser_binding.exists(identity)

    assert "success" not in response.text.lower()


@pytest.mark.parametrize(
    "backend_status, expected_status",
    [
        (401, 401),
        (500, 503),
        (502, 503),
        (503, 503),
        (504, 503),
        (None, 200),
    ],
)
def test_login_error_classification(
    environment,
    backend_status,
    expected_status,
):
    browser, _, backend = environment

    bootstrap(browser)

    backend.login_status = backend_status

    response = login(browser)

    assert response.status_code == expected_status

    if expected_status == 503:
        assert "temporarily unavailable" in response.text

    if expected_status != 200:
        assert "access-" not in response.text
        assert "refresh-" not in response.text


@pytest.mark.parametrize(
    "origin",
    [
        None,
        "https://untrusted.example",
    ],
)
def test_logout_rejects_untrusted_origin(
    environment,
    origin,
):
    browser, _, backend = environment

    bootstrap(browser)
    assert login(browser).status_code == 200

    response = logout(browser, origin=origin)

    assert response.status_code == 403
    assert backend.revoked == []


def test_logout_requires_browser_cookie(environment):
    browser, _, backend = environment

    response = logout(browser)

    assert response.status_code == 401
    assert backend.revoked == []


def test_logout_one_browser_preserves_other_browser():
    backend = FakeBackend()

    app = create_app(
        secure_cookie=False,
        api_client=backend,
        allowed_origin=ORIGIN,
    )

    try:
        with (
            TestClient(app, follow_redirects=False) as a,
            TestClient(app, follow_redirects=False) as b,
        ):
            bootstrap(a)
            bootstrap(b)

            assert login(a).status_code == 200
            assert login(b).status_code == 200

            assert logout(a).status_code == 200

            assert a.get("/frontend-auth/status").json() == {
                "authenticated": False
            }

            assert b.get("/frontend-auth/status").json() == {
                "authenticated": True
            }

            assert backend.revoked == ["refresh-1"]
    finally:
        app.state.browser_binding.close_all()