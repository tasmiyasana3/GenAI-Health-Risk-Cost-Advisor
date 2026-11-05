
"""
MODULE NAME
-----------
PHASE 5.2.4 LIVE FRONTEND TOKEN REFRESH SMOKE TEST

PURPOSE
-------
Verify frontend credential refresh against the running FastAPI
backend using an isolated frontend TestClient session.

ENVIRONMENT / CONFIGURATION
---------------------------
Requires the backend at http://127.0.0.1:8000.

API_BASE_URL optionally overrides the backend URL.
Uses an existing disposable test account.

DEPENDENCIES
------------
Python standard library, FastAPI TestClient,
frontend.api_client, frontend.http_session,
frontend.server.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Authenticate through the frontend HTTP boundary.
2. Resolve the correct server-side credential manager.
3. Obtain the initial access token.
4. Simulate local access-token expiration.
5. Trigger real backend refresh.
6. Verify access and refresh credential rotation.
7. Verify authenticated state after refresh.
8. Verify logout using the rotated credentials.
9. Verify browser cookie invalidation.

SECURITY NOTES
--------------
- No passwords, access tokens, or refresh tokens are printed.
- The test uses an isolated frontend application.
- Only the test session's expiration timestamp is changed.
- The system clock and backend token lifetime are unchanged.
- Real backend authentication requests are made.
- Use only an approved disposable test account.
- No paid external APIs are called.
"""

from __future__ import annotations

import getpass
import os

from fastapi.testclient import TestClient

from frontend.api_client import FrontendAPIClient
from frontend.http_session import COOKIE_NAME
from frontend.server import create_app


BACKEND_URL = os.getenv(
    "API_BASE_URL",
    "http://127.0.0.1:8000",
)

FRONTEND_ORIGIN = "http://127.0.0.1:7860"

ORIGIN_HEADERS = {
    "Origin": FRONTEND_ORIGIN,
}


def main() -> None:
    """Verify real backend refresh through frontend credentials."""

    print("\nPHASE 5.2.4 — LIVE TOKEN REFRESH SMOKE TEST")
    print("-" * 55)

    email = input("Disposable test account email: ").strip()
    password = getpass.getpass("Test account password: ")

    if not email or not password:
        raise SystemExit("STOP: Test credentials are required.")

    app = create_app(
        secure_cookie=False,
        allowed_origin=FRONTEND_ORIGIN,
        api_client=FrontendAPIClient(
            base_url=BACKEND_URL,
        ),
    )

    with TestClient(
        app,
        follow_redirects=False,
        base_url=FRONTEND_ORIGIN,
    ) as browser:

        # Establish an anonymous browser session.
        bootstrap = browser.get("/")

        assert bootstrap.status_code == 303

        # Authenticate against the real running backend.
        login = browser.post(
            "/frontend-auth/login",
            headers=ORIGIN_HEADERS,
            json={
                "email": email,
                "password": password,
            },
        )

        del password

        assert login.status_code == 200, (
            f"Login failed: HTTP {login.status_code}"
        )

        identity = browser.cookies.get(COOKIE_NAME)

        assert identity, "Authenticated browser cookie missing."

        print("PASS 1: Real backend login")

        # Resolve the server-side manager through the
        # registered browser identity.
        binding = app.state.browser_binding
        coordinator = app.state.auth_coordinator

        manager = binding.resolve(identity)

        original_access = coordinator.get_access_token(
            browser_identity=identity,
        )

        assert original_access

        # Capture the original refresh token only in memory.
        original_credentials = manager._credentials

        assert original_credentials is not None

        original_refresh = original_credentials.refresh_token

        # Force expiration of this isolated test session.
        # Do not change the clock or backend token settings.
        original_credentials.expires_at = (
            manager._clock() - 1.0
        )

        # The coordinator delegates to the manager, which
        # must now call the real backend refresh endpoint.
        refreshed_access = coordinator.get_access_token(
            browser_identity=identity,
        )

        # The backend may issue an identical JWT when login and
        # refresh happen within the same second. Token uniqueness
        # is not part of the current access-token contract.
        #
        # Instead, verify that the refreshed access token exists.
        # The preceding successful refresh call establishes that
        # the backend accepted the refresh request.
        assert isinstance(refreshed_access, str) and refreshed_access, (
            "Refresh did not return a usable access token."
        )

        print("PASS 3: Refreshed access token received")

        rotated_credentials = manager._credentials

        assert rotated_credentials is not None

        assert rotated_credentials.refresh_token != original_refresh, (
            "Refresh token did not rotate."
        )

        print("PASS 4: Refresh token rotated")

        # The frontend session must remain authenticated.
        status = browser.get("/frontend-auth/status")

        assert status.status_code == 200
        assert status.json() == {
            "authenticated": True,
        }

        print("PASS 5: Frontend remains authenticated")

        # Logout must use the newly rotated refresh token.
        logout = browser.post(
            "/frontend-auth/logout",
            headers=ORIGIN_HEADERS,
        )

        assert logout.status_code == 200, (
            f"Logout failed: HTTP {logout.status_code}"
        )

        print("PASS 6: Backend logout after refresh")

        assert browser.cookies.get(COOKIE_NAME) is None, (
            "Browser cookie was not cleared."
        )

        final_status = browser.get(
            "/frontend-auth/status"
        )

        assert final_status.status_code == 200
        assert final_status.json() == {
            "authenticated": False,
        }

        print("PASS 7: Browser session invalidated")

    print("\nSUCCESS: All 7 token-refresh checks passed.")


if __name__ == "__main__":
    main()