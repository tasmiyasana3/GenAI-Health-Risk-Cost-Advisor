
"""
MODULE NAME
-----------
GRADIO AUTHENTICATION ADAPTER UNIT TESTS

PURPOSE
-------
Verify the authentication adapter's security behavior
without external services or application startup.

RESPONSIBILITIES
----------------
- Reject missing browser identities.
- Reject anonymous browser sessions.
- Reject expired or invalid credential bindings.
- Accept server-validated authenticated identities.
- Verify that internal credentials are never returned.
- Verify that unexpected errors are not silently hidden.

ARCHITECTURE / DESIGN
---------------------
Tests use unittest.mock to isolate the adapter from
HTTP cookies and the browser session registry.

SECURITY CONSIDERATIONS
-----------------------
- No real JWTs or passwords are used.
- No backend or Gemini requests are performed.
- Successful authentication is not treated as Gradio
  session ownership authorization.

NOTES
-----
Run with pytest from the repository root.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from frontend.api_client import FrontendAPIError
from frontend.browser_session_binding import BrowserSessionBinding
from frontend.gradio_auth import GradioAuthenticationAdapter
from frontend.http_session import HTTPSessionCookies


TEST_IDENTITY = "fictional-browser-identity"


@pytest.fixture
def dependencies():
    """
    Build isolated dependency mocks.

    No real credential manager, database, or network
    client is constructed.
    """

    cookies = Mock(spec=HTTPSessionCookies)
    binding = Mock(spec=BrowserSessionBinding)
    request = Mock()

    adapter = GradioAuthenticationAdapter(
        cookies=cookies,
        binding=binding,
    )

    return adapter, cookies, binding, request


def test_missing_browser_identity_is_rejected(
    dependencies,
) -> None:
    """A missing cookie must not authenticate a browser."""

    adapter, cookies, binding, request = dependencies

    cookies.read_identity.return_value = None

    result = adapter(request)

    assert result is None

    binding.resolve.assert_not_called()


def test_anonymous_browser_is_rejected(
    dependencies,
) -> None:
    """
    A registered browser without authenticated
    credentials must not access protected Gradio.
    """

    adapter, cookies, binding, request = dependencies

    cookies.read_identity.return_value = TEST_IDENTITY

    binding.resolve.side_effect = FrontendAPIError(
        "Browser session is not authenticated."
    )

    result = adapter(request)

    assert result is None

    binding.resolve.assert_called_once_with(
        TEST_IDENTITY
    )


def test_expired_browser_session_is_rejected(
    dependencies,
) -> None:
    """Expired credential bindings must fail closed."""

    adapter, cookies, binding, request = dependencies

    cookies.read_identity.return_value = TEST_IDENTITY

    binding.resolve.side_effect = FrontendAPIError(
        "Browser session has expired."
    )

    result = adapter(request)

    assert result is None


def test_authenticated_browser_is_accepted(
    dependencies,
) -> None:
    """
    A registered browser with an authenticated
    credential manager may pass the auth dependency.
    """

    adapter, cookies, binding, request = dependencies

    cookies.read_identity.return_value = TEST_IDENTITY

    credential_manager = object()

    binding.resolve.return_value = credential_manager

    result = adapter(request)

    assert result == TEST_IDENTITY

    binding.resolve.assert_called_once_with(
        TEST_IDENTITY
    )


def test_credentials_are_not_returned(
    dependencies,
) -> None:
    """
    Authentication must not expose the internal
    credential-manager object.
    """

    adapter, cookies, binding, request = dependencies

    cookies.read_identity.return_value = TEST_IDENTITY

    credential_manager = object()

    binding.resolve.return_value = credential_manager

    result = adapter(request)

    assert result == TEST_IDENTITY
    assert result is not credential_manager


def test_unexpected_errors_are_not_silently_accepted(
    dependencies,
) -> None:
    """
    Unexpected programming failures must not result
    in successful authentication.
    """

    adapter, cookies, binding, request = dependencies

    cookies.read_identity.return_value = TEST_IDENTITY

    binding.resolve.side_effect = RuntimeError(
        "Unexpected internal failure."
    )

    with pytest.raises(RuntimeError):
        adapter(request)