
"""
MODULE NAME
-----------
PHASE 5.2.4 FRONTEND AUTHENTICATION HTTP TESTS

PURPOSE
-------
Verify frontend HTTP login, browser-cookie rotation,
credential confidentiality, and browser-session isolation.

ENVIRONMENT / CONFIGURATION
---------------------------
Runs locally with pytest and FastAPI TestClient.

No running backend, PostgreSQL, Gemini API, or external
network access is required.

DEPENDENCIES
------------
pytest
fastapi.testclient
frontend.api_client
frontend.http_session
frontend.server

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
- Successful login rotates the browser cookie.
- The old browser cookie becomes invalid.
- Backend credentials never appear in HTTP responses.
- Invalid login preserves the anonymous browser session.
- Missing or foreign Origin headers are rejected.
- Missing browser identity is rejected.
- Two independent browsers remain isolated.
- Existing Gradio event endpoints remain blocked.

SECURITY NOTES
--------------
Synthetic credentials only.

A passing result verifies the HTTP behavior under test,
not live backend authentication or production CSRF security.
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

LOGIN_PATH = "/frontend-auth/login"
STATUS_PATH = "/frontend-auth/status"

VALID_LOGIN = {
    "email": "test@example.test",
    "password": "correct-password",
}


class FakeAuthenticationAPI:
    """Provide isolated synthetic backend credentials."""

    def __init__(self) -> None:
        self.login_count = 0
        self.revoked_tokens: list[str] = []

    def login(
        self,
        email: str,
        password: str,
    ) -> AuthenticationCredentials:
        if password != "correct-password":
            raise FrontendAPIError(
                "Invalid credentials.",
                status_code=401,
            )

        self.login_count += 1

        return AuthenticationCredentials(
            access_token=f"secret-access-{self.login_count}",
            refresh_token=f"secret-refresh-{self.login_count}",
            expires_in=1800,
        )

    def refresh(
        self,
        refresh_token: str,
    ) -> AuthenticationCredentials:
        raise AssertionError(
            "Refresh is not expected in these tests."
        )

    def logout(self, refresh_token: str) -> None:
        self.revoked_tokens.append(refresh_token)


@pytest.fixture
def environment():
    """Construct an isolated frontend and synthetic backend."""

    api = FakeAuthenticationAPI()

    application = create_app(
        secure_cookie=False,
        api_client=api,
        allowed_origin=ORIGIN,
    )

    with TestClient(
        application,
        follow_redirects=False,
    ) as client:
        yield client, application, api

    application.state.browser_binding.close_all()


def bootstrap(client: TestClient) -> str:
    """Create and return an anonymous browser identity."""

    response = client.get("/")

    assert response.status_code == 303

    identity = client.cookies.get(COOKIE_NAME)

    assert identity is not None

    return identity


def login(
    client: TestClient,
    *,
    origin: str = ORIGIN,
    password: str = "correct-password",
):
    """Submit a browser login with an explicit Origin."""

    return client.post(
        LOGIN_PATH,
        headers={"Origin": origin},
        json={
            "email": "test@example.test",
            "password": password,
        },
    )


def test_successful_login_rotates_cookie(environment):
    client, _, _ = environment

    old_identity = bootstrap(client)

    response = login(client)

    assert response.status_code == 200
    assert response.json() == {"authenticated": True}

    new_identity = client.cookies.get(COOKIE_NAME)

    assert new_identity is not None
    assert new_identity != old_identity

    cookie_header = response.headers["set-cookie"].lower()

    assert "httponly" in cookie_header
    assert "samesite=strict" in cookie_header

    assert client.get(STATUS_PATH).json() == {
        "authenticated": True
    }


def test_old_cookie_is_invalid_after_login(environment):
    client, _, _ = environment

    old_identity = bootstrap(client)

    assert login(client).status_code == 200

    # Restore the old identity to simulate a replay.
    client.cookies.set(COOKIE_NAME, old_identity)

    response = client.get(STATUS_PATH)

    assert response.status_code == 200
    assert response.json() == {
        "authenticated": False
    }


def test_backend_tokens_are_not_exposed(environment):
    client, _, _ = environment

    bootstrap(client)

    response = login(client)

    assert response.status_code == 200

    serialized_response = (
        response.text
        + str(dict(response.headers))
    )

    assert "secret-access-" not in serialized_response
    assert "secret-refresh-" not in serialized_response

    status = client.get(STATUS_PATH)

    assert "secret-access-" not in status.text
    assert "secret-refresh-" not in status.text


def test_invalid_password_preserves_anonymous_browser(
    environment,
):
    client, _, _ = environment

    original_identity = bootstrap(client)

    response = login(
        client,
        password="incorrect-password",
    )

    assert response.status_code == 401

    assert client.cookies.get(COOKIE_NAME) == (
        original_identity
    )

    assert client.get(STATUS_PATH).json() == {
        "authenticated": False
    }


@pytest.mark.parametrize(
    "origin",
    [
        None,
        "https://attacker.example",
        "http://127.0.0.1:7861",
    ],
)
def test_missing_or_foreign_origin_is_rejected(
    environment,
    origin,
):
    client, _, api = environment

    bootstrap(client)

    headers = (
        {"Origin": origin}
        if origin is not None
        else {}
    )

    response = client.post(
        LOGIN_PATH,
        headers=headers,
        json=VALID_LOGIN,
    )

    assert response.status_code == 403
    assert api.login_count == 0


def test_login_requires_existing_browser_cookie(environment):
    client, _, api = environment

    response = login(client)

    assert response.status_code == 401
    assert api.login_count == 0


def test_two_browser_clients_remain_isolated():
    api = FakeAuthenticationAPI()

    application = create_app(
        secure_cookie=False,
        api_client=api,
        allowed_origin=ORIGIN,
    )

    try:
        with (
            TestClient(
                application,
                follow_redirects=False,
            ) as browser_a,
            TestClient(
                application,
                follow_redirects=False,
            ) as browser_b,
        ):
            bootstrap(browser_a)
            bootstrap(browser_b)

            assert login(browser_a).status_code == 200

            assert browser_a.get(STATUS_PATH).json() == {
                "authenticated": True
            }

            assert browser_b.get(STATUS_PATH).json() == {
                "authenticated": False
            }

            assert login(browser_b).status_code == 200

            assert browser_b.get(STATUS_PATH).json() == {
                "authenticated": True
            }

            assert (
                browser_a.cookies.get(COOKIE_NAME)
                != browser_b.cookies.get(COOKIE_NAME)
            )

    finally:
        application.state.browser_binding.close_all()


def test_gradio_events_remain_blocked_after_login(
    environment,
):
    client, _, _ = environment

    bootstrap(client)

    assert login(client).status_code == 200

    response = client.post(
        "/ui/gradio_api/queue/join",
        json={},
    )

    assert response.status_code == 403