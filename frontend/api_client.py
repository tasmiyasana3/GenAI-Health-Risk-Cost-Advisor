
"""
MODULE NAME
-----------
FRONTEND FASTAPI HTTP CLIENT

PURPOSE
-------
Provide a synchronous HTTP transport layer for the Gradio
frontend to communicate with the existing FastAPI
authentication backend.

This module does not manage Gradio sessions or persist
authentication credentials. Those responsibilities belong
to a separate session-isolated credential manager.

ENVIRONMENT / CONFIGURATION
---------------------------
API_BASE_URL:
    FastAPI base URL. Defaults to http://127.0.0.1:8000.

    HTTP is permitted only for loopback addresses.
    Non-loopback connections must use HTTPS.

API_REQUEST_TIMEOUT_SECONDS:
    Optional positive request timeout. Defaults to 10 seconds.

AUTH_ALLOWED_ORIGINS:
    The backend must accept the configured API origin for
    refresh and logout operations.

COOKIE_SECURE:
    For localhost HTTP development, the backend must be
    configured appropriately. Secure cookies are required
    for HTTPS deployments.

DEPENDENCIES
------------
Python standard library, httpx.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Validate backend URL and timeout configuration.
2. Register users through FastAPI.
3. Authenticate users and extract access credentials.
4. Extract the session's refresh cookie.
5. Refresh access and refresh credentials.
6. Request backend logout.
7. Handle HTTP failures and malformed responses.
8. Avoid retaining cookies between operations.
9. Support offline tests using httpx.MockTransport.

SECURITY NOTES
--------------
- FastAPI remains responsible for authentication.
- Never log passwords, access tokens, or refresh cookies.
- Do not store user credentials in global variables.
- Never expose credentials through Gradio outputs.
- Each request creates a fresh httpx.Client.
- Cookies are configured on that temporary client, not
  on individual requests.
- A separate server-side session manager must maintain
  credentials independently for each Gradio session.
- The Origin header comes from trusted configuration.
"""

from __future__ import annotations

import os

from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlsplit

import httpx


# =============================================================================
# CONSTANTS
# =============================================================================

DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 10.0

REFRESH_COOKIE_NAME = "refresh_token"


# =============================================================================
# EXCEPTIONS
# =============================================================================

class FrontendAPIError(Exception):
    """
    Represent an error safe to display in the frontend.

    Raw backend error details are intentionally excluded
    because they may contain sensitive information.
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code


# =============================================================================
# RESPONSE DATA MODELS
# =============================================================================

@dataclass(frozen=True)
class AuthenticationCredentials:
    """
    Hold credentials returned by FastAPI authentication.

    This object contains secrets and must remain server-side.

    Do not return it directly to a Gradio component or
    include it in application logs.
    """

    access_token: str
    refresh_token: str
    expires_in: int


@dataclass(frozen=True)
class RegistrationResult:
    """Represent a successfully registered user."""

    user_id: str
    email: str
    created_at: str


# =============================================================================
# CONFIGURATION HELPERS
# =============================================================================

def validate_api_base_url(value: str) -> str:
    """
    Validate and normalize the configured FastAPI URL.

    HTTP is restricted to loopback hosts so that credentials
    are not transmitted over unencrypted remote connections.
    """

    parsed = urlsplit(value.strip())

    if parsed.scheme not in {"http", "https"}:
        raise ValueError(
            "API_BASE_URL must use HTTP or HTTPS."
        )

    if not parsed.hostname:
        raise ValueError(
            "API_BASE_URL must contain a hostname."
        )

    if parsed.username or parsed.password:
        raise ValueError(
            "API_BASE_URL must not contain credentials."
        )

    if parsed.path not in {"", "/"}:
        raise ValueError(
            "API_BASE_URL must not contain a path."
        )

    if parsed.query or parsed.fragment:
        raise ValueError(
            "API_BASE_URL must not contain query parameters "
            "or fragments."
        )

    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError(
            "API_BASE_URL contains an invalid port."
        ) from error

    if parsed.scheme == "http":
        if parsed.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise ValueError(
                "HTTP is permitted only for loopback APIs."
            )

    hostname = parsed.hostname.lower()

    if ":" in hostname:
        hostname = f"[{hostname}]"

    default_port = (
        (parsed.scheme == "http" and port == 80)
        or (parsed.scheme == "https" and port == 443)
    )

    port_suffix = (
        f":{port}"
        if port is not None and not default_port
        else ""
    )

    return f"{parsed.scheme}://{hostname}{port_suffix}"


def get_api_timeout() -> float:
    """Read and validate the configured HTTP request timeout."""

    raw_value = os.getenv(
        "API_REQUEST_TIMEOUT_SECONDS",
        str(DEFAULT_TIMEOUT_SECONDS),
    )

    try:
        timeout = float(raw_value)
    except ValueError as error:
        raise ValueError(
            "API_REQUEST_TIMEOUT_SECONDS must be numeric."
        ) from error

    if not 0 < timeout < float("inf"):
        raise ValueError(
            "API_REQUEST_TIMEOUT_SECONDS must be finite "
            "and greater than zero."
        )

    return timeout


# =============================================================================
# HTTP CLIENT
# =============================================================================

class FrontendAPIClient:
    """
    Provide request-scoped communication with FastAPI.

    The class does not retain an httpx.Client or cookie jar
    between operations.

    A custom transport can be supplied for offline tests.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        configured_url = (
            base_url
            if base_url is not None
            else os.getenv(
                "API_BASE_URL",
                DEFAULT_API_BASE_URL,
            )
        )

        self.base_url = validate_api_base_url(
            configured_url
        )

        self.timeout = (
            get_api_timeout()
            if timeout is None
            else float(timeout)
        )

        if not 0 < self.timeout < float("inf"):
            raise ValueError(
                "Request timeout must be finite "
                "and greater than zero."
            )

        self._transport = transport

    # -------------------------------------------------------------------------
    # INTERNAL REQUEST HANDLING
    # -------------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_data: Mapping[str, Any] | None = None,
        refresh_token: str | None = None,
        send_origin: bool = False,
    ) -> tuple[dict[str, Any], str | None]:
        """
        Send one HTTP request and validate its response.

        A new httpx.Client is created for each operation.
        Therefore, its cookie jar cannot accidentally be
        reused by another frontend operation.

        Refresh cookies are supplied explicitly by the
        future session-isolated credential manager.
        """

        headers = {
            "Accept": "application/json",
        }

        if send_origin:
            headers["Origin"] = self.base_url

        # Cookies belong to the temporary HTTP client.
        # This avoids the deprecated per-request cookies
        # argument and keeps cookie storage request-scoped.
        cookies = None

        if refresh_token is not None:
            if not refresh_token:
                raise FrontendAPIError(
                    "Authentication session is unavailable."
                )

            cookies = {
                REFRESH_COOKIE_NAME: refresh_token,
            }

        try:
            with httpx.Client(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self._transport,
                trust_env=False,
                follow_redirects=False,
                cookies=cookies,
            ) as client:

                response = client.request(
                    method=method,
                    url=path,
                    headers=headers,
                    json=json_data,
                )

                # Authentication requests should not silently
                # follow redirects to unexpected destinations.
                if response.is_redirect:
                    raise FrontendAPIError(
                        "Unexpected backend redirect.",
                        response.status_code,
                    )

                if response.status_code >= 400:
                    self._raise_api_error(response)

                try:
                    payload = response.json()
                except ValueError as error:
                    raise FrontendAPIError(
                        "Backend returned an invalid response."
                    ) from error

                if not isinstance(payload, dict):
                    raise FrontendAPIError(
                        "Backend returned an unexpected "
                        "response structure."
                    )

                # Read only the cookie set by this response.
                # Do not return the entire client cookie jar.
                new_refresh_token = response.cookies.get(
                    REFRESH_COOKIE_NAME
                )

                return payload, new_refresh_token

        except httpx.TimeoutException as error:
            raise FrontendAPIError(
                "The backend request timed out."
            ) from error

        except httpx.RequestError as error:
            raise FrontendAPIError(
                "Unable to connect to the backend."
            ) from error

    @staticmethod
    def _raise_api_error(
        response: httpx.Response,
    ) -> None:
        """
        Convert HTTP failures into safe application errors.

        Arbitrary backend error messages are deliberately
        excluded from the user-facing exception.
        """

        status_code = response.status_code

        messages = {
            400: "The request was invalid.",
            401: "Authentication failed or the session expired.",
            403: "Access to this operation was denied.",
            404: "The requested resource was not found.",
            409: "The request conflicts with existing data.",
            413: "The uploaded content is too large.",
            422: "The submitted information is invalid.",
            429: "Too many requests. Please try again later.",
            500: "The backend encountered an error.",
            502: "The backend is temporarily unavailable.",
            503: "The backend is temporarily unavailable.",
            504: "The backend request timed out.",
        }

        message = messages.get(
            status_code,
            "The backend could not complete the request.",
        )

        raise FrontendAPIError(
            message,
            status_code=status_code,
        )

    # -------------------------------------------------------------------------
    # AUTHENTICATION RESPONSE VALIDATION
    # -------------------------------------------------------------------------

    @staticmethod
    def _parse_authentication_response(
        payload: Mapping[str, Any],
        refresh_token: str | None,
    ) -> AuthenticationCredentials:
        """
        Validate authentication credentials returned by FastAPI.

        Both the access token and refresh cookie must be
        present before the response is considered valid.
        """

        access_token = payload.get("access_token")
        token_type = payload.get("token_type")
        expires_in = payload.get("expires_in")

        if (
            not isinstance(access_token, str)
            or not access_token
            or not isinstance(token_type, str)
            or token_type.lower() != "bearer"
            or type(expires_in) is not int
            or expires_in <= 0
            or not isinstance(refresh_token, str)
            or not refresh_token
        ):
            raise FrontendAPIError(
                "Backend returned incomplete "
                "authentication credentials."
            )

        return AuthenticationCredentials(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
        )

    # -------------------------------------------------------------------------
    # REGISTRATION
    # -------------------------------------------------------------------------

    def register(
        self,
        email: str,
        password: str,
    ) -> RegistrationResult:
        """
        Register a user through the existing FastAPI endpoint.

        Registration does not automatically log in the user.
        """

        payload, _ = self._request(
            "POST",
            "/auth/register",
            json_data={
                "email": email,
                "password": password,
            },
        )

        required_fields = (
            "user_id",
            "email",
            "created_at",
        )

        if any(
            not isinstance(payload.get(field), str)
            or not payload[field]
            for field in required_fields
        ):
            raise FrontendAPIError(
                "Backend returned incomplete "
                "registration information."
            )

        return RegistrationResult(
            user_id=payload["user_id"],
            email=payload["email"],
            created_at=payload["created_at"],
        )

    # -------------------------------------------------------------------------
    # LOGIN
    # -------------------------------------------------------------------------

    def login(
        self,
        email: str,
        password: str,
    ) -> AuthenticationCredentials:
        """
        Authenticate a user through FastAPI.

        The returned credentials must be stored by the
        server-side session manager, not Gradio components.
        """

        payload, refresh_token = self._request(
            "POST",
            "/auth/login",
            json_data={
                "email": email,
                "password": password,
            },
        )

        return self._parse_authentication_response(
            payload,
            refresh_token,
        )

    # -------------------------------------------------------------------------
    # REFRESH
    # -------------------------------------------------------------------------

    def refresh(
        self,
        refresh_token: str,
    ) -> AuthenticationCredentials:
        """
        Rotate credentials using the existing refresh endpoint.

        The caller must atomically replace both credentials
        in the appropriate server-side session record.
        """

        if not refresh_token:
            raise FrontendAPIError(
                "Authentication session is unavailable."
            )

        payload, new_refresh_token = self._request(
            "POST",
            "/auth/refresh",
            refresh_token=refresh_token,
            send_origin=True,
        )

        return self._parse_authentication_response(
            payload,
            new_refresh_token,
        )

    # -------------------------------------------------------------------------
    # LOGOUT
    # -------------------------------------------------------------------------

    def logout(
        self,
        refresh_token: str,
    ) -> None:
        """
        Request revocation of the current backend session.

        A successful return means FastAPI acknowledged logout.
        The caller must separately clear local credentials.
        """

        if not refresh_token:
            raise FrontendAPIError(
                "Authentication session is unavailable."
            )

        payload, _ = self._request(
            "POST",
            "/auth/logout",
            refresh_token=refresh_token,
            send_origin=True,
        )

        if not isinstance(payload.get("message"), str):
            raise FrontendAPIError(
                "Backend returned an invalid logout response."
            )