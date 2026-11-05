
"""
MODULE NAME
-----------
PHASE 5.2.4 AUTHENTICATION ROLLBACK TESTS

PURPOSE
-------
Verify compensating cleanup when backend authentication
succeeds but frontend browser binding fails.

ENVIRONMENT / CONFIGURATION
---------------------------
Offline pytest tests. No database, server, API key, or
external service is required.

DEPENDENCIES
------------
pytest
frontend.api_client
frontend.auth_coordinator
frontend.browser_session_binding
frontend.session_binding

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
- Browser binding failure triggers backend logout.
- Failed backend rollback does not hide binding failure.
- Original anonymous browser identity is not authenticated.
- Backend revocation uncertainty is logged without secrets.

SECURITY NOTES
--------------
All credentials are synthetic.
Tests do not contact real authentication endpoints.
"""

from __future__ import annotations

import logging

import pytest

from frontend.api_client import (
    AuthenticationCredentials,
    FrontendAPIError,
)
from frontend.auth_coordinator import (
    FrontendAuthenticationCoordinator,
)
from frontend.browser_session_binding import BrowserSessionBinding
from frontend.session_binding import SessionRegistry


class FakeAPI:
    """Provide synthetic authentication responses."""

    def __init__(self, *, fail_logout: bool = False) -> None:
        self.fail_logout = fail_logout
        self.logout_attempts = 0

    def login(
        self,
        email: str,
        password: str,
    ) -> AuthenticationCredentials:
        return AuthenticationCredentials(
            access_token="synthetic-access",
            refresh_token="synthetic-refresh",
            expires_in=1800,
        )

    def refresh(
        self,
        refresh_token: str,
    ) -> AuthenticationCredentials:
        raise AssertionError(
            "Refresh is not expected in this test."
        )

    def logout(self, refresh_token: str) -> None:
        self.logout_attempts += 1

        if self.fail_logout:
            raise FrontendAPIError(
                "Synthetic backend logout failure."
            )


class FailingBrowserBinding(BrowserSessionBinding):
    """Simulate failure while attaching credentials."""

    def authenticate(self, browser_identity, manager):
        raise RuntimeError("Synthetic binding failure.")


@pytest.mark.parametrize(
    "fail_logout",
    [False, True],
)
def test_binding_failure_preserves_original_error(
    fail_logout: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Backend logout must be attempted after binding failure.

    The original binding error must remain observable even
    when the compensating backend logout also fails.
    """

    api = FakeAPI(fail_logout=fail_logout)
    binding = FailingBrowserBinding(SessionRegistry())

    coordinator = FrontendAuthenticationCoordinator(
        api_client=api,
        browser_binding=binding,
    )

    identity = binding.create()

    try:
        with caplog.at_level(logging.WARNING):
            with pytest.raises(
                RuntimeError,
                match="Synthetic binding failure",
            ):
                coordinator.login(
                    browser_identity=identity,
                    email="example@example.test",
                    password="synthetic-password",
                )

        assert api.logout_attempts == 1
        assert binding.exists(identity)

        assert not coordinator.is_authenticated(
            browser_identity=identity
        )

        if fail_logout:
            assert (
                "remote session revocation is unconfirmed"
                in caplog.text
            )
            assert (
                "Synthetic backend logout failure"
                not in caplog.text
            )
        else:
            assert (
                "remote session revocation is unconfirmed"
                not in caplog.text
            )
    finally:
        binding.close_all()