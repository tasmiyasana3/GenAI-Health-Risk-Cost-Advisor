
"""
MODULE NAME
-----------
GRADIO EXECUTION AUTHORIZER UNIT TESTS

PURPOSE
-------
Verify execution-time authorization without Gradio,
PostgreSQL, network requests, or external APIs.

ENVIRONMENT / CONFIGURATION
---------------------------
Run using pytest from the repository root.

DEPENDENCIES
------------
pytest
unittest.mock
frontend.gradio_execution_authorizer

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
- Successful authorized execution.
- Missing browser identity.
- Missing Gradio session hash.
- Cross-browser or revoked ownership.
- Credential refresh failure.
- Empty backend credentials.

ARCHITECTURE / DESIGN
---------------------
Mocks isolate the execution guard from the issuer and
credential manager so authorization decisions can be
tested deterministically.

SECURITY CONSIDERATIONS
-----------------------
No real JWTs, passwords, databases, or external services
are used.

A successful mock test does not certify the complete
Gradio execution pipeline.

NOTES
-----
Integration tests are required before enabling callbacks.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from frontend.api_client import FrontendAPIError
from frontend.gradio_execution_authorizer import (
    GradioExecutionAuthorizer,
)
from frontend.gradio_session_issuer import (
    TrustedGradioSessionIssuer,
)


@pytest.fixture
def dependencies():
    """Create an isolated authorizer and its dependencies."""

    issuer = Mock(spec=TrustedGradioSessionIssuer)
    manager = Mock()

    issuer.verify.return_value = manager
    manager.get_access_token.return_value = (
        "synthetic-test-access-token"
    )

    authorizer = GradioExecutionAuthorizer(issuer)

    return authorizer, issuer, manager


def test_valid_execution_returns_server_credentials(
    dependencies,
) -> None:
    """An authorized browser receives server-side context."""

    authorizer, issuer, manager = dependencies

    result = authorizer.authorize(
        browser_identity="browser-a",
        session_hash="trusted-hash-a",
    )

    assert result.access_token == (
        "synthetic-test-access-token"
    )

    issuer.verify.assert_called_once_with(
        "browser-a",
        "trusted-hash-a",
    )

    manager.get_access_token.assert_called_once_with()


@pytest.mark.parametrize(
    "identity",
    [None, "", 123],
)
def test_invalid_browser_identity_is_rejected(
    dependencies,
    identity,
) -> None:
    """Untrusted browser identities cannot be authorized."""

    authorizer, issuer, _ = dependencies

    with pytest.raises(FrontendAPIError):
        authorizer.authorize(
            browser_identity=identity,
            session_hash="trusted-hash-a",
        )

    issuer.verify.assert_not_called()


@pytest.mark.parametrize(
    "session_hash",
    [None, "", 123],
)
def test_invalid_session_hash_is_rejected(
    dependencies,
    session_hash,
) -> None:
    """Missing or malformed session identifiers fail closed."""

    authorizer, issuer, _ = dependencies

    with pytest.raises(FrontendAPIError):
        authorizer.authorize(
            browser_identity="browser-a",
            session_hash=session_hash,
        )

    issuer.verify.assert_not_called()


def test_cross_browser_session_is_rejected(
    dependencies,
) -> None:
    """Issuer ownership failure must prevent execution."""

    authorizer, issuer, manager = dependencies

    issuer.verify.side_effect = FrontendAPIError(
        "Gradio session is not authorized."
    )

    with pytest.raises(FrontendAPIError):
        authorizer.authorize(
            browser_identity="browser-b",
            session_hash="trusted-hash-a",
        )

    manager.get_access_token.assert_not_called()


def test_failed_refresh_prevents_execution(
    dependencies,
) -> None:
    """Expired credentials cannot be silently accepted."""

    authorizer, _, manager = dependencies

    manager.get_access_token.side_effect = (
        FrontendAPIError(
            "Credential refresh failed."
        )
    )

    with pytest.raises(FrontendAPIError):
        authorizer.authorize(
            browser_identity="browser-a",
            session_hash="trusted-hash-a",
        )


@pytest.mark.parametrize(
    "token",
    [None, "", 123],
)
def test_invalid_access_token_is_rejected(
    dependencies,
    token,
) -> None:
    """The guard must not return invalid credentials."""

    authorizer, _, manager = dependencies

    manager.get_access_token.return_value = token

    with pytest.raises(FrontendAPIError):
        authorizer.authorize(
            browser_identity="browser-a",
            session_hash="trusted-hash-a",
        )