
"""
MODULE NAME
-----------
GRADIO PROTECTED CALLBACK TESTS

PURPOSE
-------
Verify that protected callbacks authorize execution using
trusted Gradio request context.

ENVIRONMENT / CONFIGURATION
---------------------------
Local pytest execution. No backend or paid API calls.

DEPENDENCIES
------------
pytest
unittest.mock
frontend.gradio_protected_callbacks

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
- Valid authenticated execution.
- Missing request context.
- Missing browser identity.
- Missing session hash.
- Rejected execution authorization.
- No credential exposure in successful output.

ARCHITECTURE / DESIGN
---------------------
Mock request and authorizer -> protected callback -> assertions.

SECURITY CONSIDERATIONS
-----------------------
These tests verify callback-level behavior only.
They do not establish HTTP gate or queue security.

NOTES
-----
Full HTTP and queued execution integration tests are
required before Phase 5.2.6C can be closed.
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from frontend.api_client import FrontendAPIError
from frontend.gradio_protected_callbacks import (
    ProtectedGradioCallbacks,
)


def make_request(
    username="browser-a",
    session_hash="trusted-session-a",
):
    """Construct a minimal Gradio-like request context."""
    return SimpleNamespace(
        username=username,
        session_hash=session_hash,
    )


def test_valid_execution_is_authorized():
    authorizer = Mock()
    callbacks = ProtectedGradioCallbacks(authorizer)

    result = callbacks.verify_session(make_request())

    authorizer.authorize.assert_called_once_with(
        browser_identity="browser-a",
        session_hash="trusted-session-a",
    )

    assert result == "Authenticated session verified."


def test_missing_request_is_rejected():
    callbacks = ProtectedGradioCallbacks(Mock())

    with pytest.raises(FrontendAPIError):
        callbacks.verify_session(None)


def test_missing_identity_is_forwarded_for_rejection():
    authorizer = Mock()
    authorizer.authorize.side_effect = FrontendAPIError(
        "Unauthorized."
    )

    callbacks = ProtectedGradioCallbacks(authorizer)

    with pytest.raises(FrontendAPIError):
        callbacks.verify_session(
            make_request(username=None)
        )

    authorizer.authorize.assert_called_once_with(
        browser_identity=None,
        session_hash="trusted-session-a",
    )


def test_missing_hash_is_forwarded_for_rejection():
    authorizer = Mock()
    authorizer.authorize.side_effect = FrontendAPIError(
        "Unauthorized."
    )

    callbacks = ProtectedGradioCallbacks(authorizer)

    with pytest.raises(FrontendAPIError):
        callbacks.verify_session(
            make_request(session_hash=None)
        )


def test_authorization_failure_prevents_success():
    authorizer = Mock()
    authorizer.authorize.side_effect = FrontendAPIError(
        "Session revoked."
    )

    callbacks = ProtectedGradioCallbacks(authorizer)

    with pytest.raises(FrontendAPIError):
        callbacks.verify_session(make_request())


def test_success_does_not_expose_credentials():
    authorizer = Mock()
    authorizer.authorize.return_value = SimpleNamespace(
        access_token="secret-backend-token"
    )

    callbacks = ProtectedGradioCallbacks(authorizer)

    result = callbacks.verify_session(make_request())

    assert "secret-backend-token" not in result