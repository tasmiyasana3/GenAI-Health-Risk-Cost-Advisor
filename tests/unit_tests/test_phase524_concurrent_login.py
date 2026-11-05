
"""
MODULE NAME
-----------
PHASE 5.2.4 CONCURRENT LOGIN TESTS

PURPOSE
-------
Verify that simultaneous authentication attempts using
one browser identity cannot both become authenticated.

ENVIRONMENT / CONFIGURATION
---------------------------
Offline pytest.
No database, external HTTP requests, Gemini, or paid services.

DEPENDENCIES
------------
Python threading and concurrent.futures.
pytest.
Existing frontend authentication components.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
- Two simultaneous logins cannot reuse one browser identity.
- Exactly one browser identity rotation succeeds.
- The unsuccessful backend login is rolled back.
- The winning session remains authenticated.

SECURITY NOTES
--------------
All credentials are synthetic.
No real tokens, passwords, or customer information.
This is a deterministic concurrency test, not a load test.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from frontend.api_client import (
    AuthenticationCredentials,
    FrontendAPIError,
)
from frontend.auth_coordinator import (
    FrontendAuthenticationCoordinator,
)
from frontend.browser_session_binding import BrowserSessionBinding
from frontend.session_binding import SessionRegistry


class ConcurrentFakeAPI:
    """Coordinate two backend logins before browser binding."""

    def __init__(self) -> None:
        self.barrier = threading.Barrier(2, timeout=5)
        self.lock = threading.Lock()
        self.counter = 0
        self.revoked_tokens: list[str] = []

    def login(
        self,
        email: str,
        password: str,
    ) -> AuthenticationCredentials:
        with self.lock:
            self.counter += 1
            number = self.counter

        credentials = AuthenticationCredentials(
            access_token=f"access-{number}",
            refresh_token=f"refresh-{number}",
            expires_in=1800,
        )

        # Both backend logins finish before either request
        # can attach credentials to the browser identity.
        self.barrier.wait()

        return credentials

    def refresh(
        self,
        refresh_token: str,
    ) -> AuthenticationCredentials:
        raise AssertionError(
            "Refresh is not expected in this test."
        )

    def logout(self, refresh_token: str) -> None:
        with self.lock:
            self.revoked_tokens.append(refresh_token)


def test_simultaneous_login_allows_one_browser_owner() -> None:
    """
    Two requests race to authenticate one browser identity.

    The winner rotates the identity. The loser must fail
    and revoke the backend session it created.
    """

    api = ConcurrentFakeAPI()
    binding = BrowserSessionBinding(SessionRegistry())

    coordinator = FrontendAuthenticationCoordinator(
        api_client=api,
        browser_binding=binding,
    )

    original_identity = binding.create()

    def attempt_login():
        try:
            identity = coordinator.login(
                browser_identity=original_identity,
                email="same-user@example.test",
                password="synthetic-password",
            )
            return ("success", identity)
        except FrontendAPIError:
            return ("rejected", None)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(attempt_login)
                for _ in range(2)
            ]

            results = [
                future.result(timeout=10)
                for future in futures
            ]

        successes = [
            identity
            for status, identity in results
            if status == "success"
        ]

        rejections = [
            status
            for status, _ in results
            if status == "rejected"
        ]

        assert len(successes) == 1
        assert len(rejections) == 1

        winning_identity = successes[0]

        assert winning_identity is not None
        assert winning_identity != original_identity
        assert not binding.exists(original_identity)

        assert coordinator.is_authenticated(
            browser_identity=winning_identity
        )

        # The losing backend session must be revoked.
        assert len(api.revoked_tokens) == 1

        active_manager = binding.resolve(
            winning_identity
        )

        # Only the winning credential remains usable.
        active_token = active_manager.get_access_token()

        assert active_token in {
            "access-1",
            "access-2",
        }

        losing_number = (
            "2" if active_token == "access-1" else "1"
        )

        assert api.revoked_tokens == [
            f"refresh-{losing_number}"
        ]

    finally:
        binding.close_all()