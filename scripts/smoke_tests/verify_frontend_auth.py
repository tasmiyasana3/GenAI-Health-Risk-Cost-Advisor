"""
MODULE NAME
-----------
FRONTEND AUTHENTICATION LIVE SMOKE TEST

PURPOSE
-------
Verify real HTTP communication between the secured frontend
and the FastAPI authentication backend.

ENVIRONMENT / CONFIGURATION
---------------------------
Requires:
- Frontend running locally at http://127.0.0.1:7860
- Backend running locally at http://127.0.0.1:8000
- An existing disposable test account

FRONTEND_SMOKE_BASE_URL optionally overrides the frontend URL.

DEPENDENCIES
------------
httpx and Python standard library.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
- Anonymous browser session bootstrap.
- Browser cookie creation.
- Independent anonymous browser sessions.
- Live login through the frontend.
- Browser identity rotation.
- Authentication status.
- Isolation between authenticated and anonymous browsers.
- Live logout and local session invalidation.

SECURITY NOTES
--------------
- Credentials are entered interactively.
- Passwords and tokens are never printed.
- The test does not inspect or expose backend JWTs.
- Run against a disposable account in an approved test environment.
- No paid external APIs are called.
"""

from __future__ import annotations

import getpass
import os

import httpx


BASE_URL = os.getenv(
    "FRONTEND_SMOKE_BASE_URL",
    "http://127.0.0.1:7860",
).rstrip("/")

COOKIE_NAME = "health_advisor_browser_session"
ORIGIN_HEADERS = {"Origin": BASE_URL}


def create_browser() -> httpx.Client:
    """Create an isolated HTTP client with its own cookie jar."""

    return httpx.Client(
        base_url=BASE_URL,
        follow_redirects=False,
        timeout=15.0,
        trust_env=False,
    )


def bootstrap(browser: httpx.Client) -> str:
    """Initialize an anonymous browser and return its identity."""

    response = browser.get("/")

    assert response.status_code == 303, (
        f"Bootstrap failed: HTTP {response.status_code}"
    )

    identity = browser.cookies.get(COOKIE_NAME)

    assert identity, "Browser session cookie was not created."

    return identity


def authentication_status(browser: httpx.Client) -> bool:
    """Read the frontend's non-sensitive authentication status."""

    response = browser.get("/frontend-auth/status")

    assert response.status_code == 200, (
        f"Status request failed: HTTP {response.status_code}"
    )

    payload = response.json()

    assert isinstance(payload.get("authenticated"), bool), (
        "Invalid authentication status response."
    )

    return payload["authenticated"]


def main() -> None:
    """Execute the live authentication smoke-test sequence."""

    print("\nPHASE 5.2.4 — FRONTEND AUTHENTICATION SMOKE TEST")
    print("-" * 55)

    with create_browser() as browser_a, create_browser() as browser_b:

        # Test 1: Anonymous bootstrap.
        anonymous_a = bootstrap(browser_a)
        anonymous_b = bootstrap(browser_b)

        assert anonymous_a != anonymous_b, (
            "Two browsers received the same session identity."
        )

        assert authentication_status(browser_a) is False
        assert authentication_status(browser_b) is False

        print("PASS 1: Anonymous browser bootstrap")
        print("PASS 2: Two independent anonymous browsers")

        # Test 2: Real authentication.
        email = input("\nDisposable test account email: ").strip()
        password = getpass.getpass("Test account password: ")

        assert email, "Test email cannot be empty."
        assert password, "Test password cannot be empty."

        response = browser_a.post(
            "/frontend-auth/login",
            headers=ORIGIN_HEADERS,
            json={
                "email": email,
                "password": password,
            },
        )

        # Release the local password reference after submission.
        del password

        assert response.status_code == 200, (
            f"Login failed: HTTP {response.status_code}"
        )

        authenticated_a = browser_a.cookies.get(COOKIE_NAME)

        assert authenticated_a
        assert authenticated_a != anonymous_a, (
            "Browser identity was not rotated after login."
        )

        assert authentication_status(browser_a) is True

        print("PASS 3: Live frontend-to-backend login")
        print("PASS 4: Browser identity rotation")

        # Test 3: Authenticated browser isolation.
        assert authentication_status(browser_b) is False

        print("PASS 5: Browser B remains unauthenticated")

        # Test 4: Real logout.
        response = browser_a.post(
            "/frontend-auth/logout",
            headers=ORIGIN_HEADERS,
        )

        assert response.status_code == 200, (
            f"Logout failed: HTTP {response.status_code}"
        )

        assert browser_a.cookies.get(COOKIE_NAME) is None, (
            "Browser cookie was not cleared after logout."
        )

        assert authentication_status(browser_a) is False
        assert authentication_status(browser_b) is False

        print("PASS 6: Live backend logout")
        print("PASS 7: Frontend cookie invalidation")
        print("PASS 8: Browser isolation after logout")

    print("\nSUCCESS: All 8 live authentication checks passed.")


if __name__ == "__main__":
    main()
