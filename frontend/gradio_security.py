
"""
MODULE NAME
-----------
GRADIO HTTP SECURITY GATE

PURPOSE
-------
Enforce a restrictive, fail-closed HTTP security boundary
around the pre-authentication Gradio frontend.

ENVIRONMENT / CONFIGURATION
---------------------------
Single-process frontend ASGI deployment.

Gradio is mounted at /ui by default.

No database, Gemini API, or external HTTP requests are
performed by this module.

DEPENDENCIES
------------
Starlette.
frontend.http_session.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
- Require a registered browser identity for Gradio routes.
- Permit explicitly approved public shell resources.
- Permit GET and HEAD only.
- Allow Gradio's bundled JavaScript, CSS, and font resources.
- Reject Gradio API, queue, event, upload, and file routes.
- Reject unknown routes and unsafe HTTP methods.
- Preserve fail-closed behavior for unrecognized endpoints.

SECURITY NOTES
--------------
This module protects a deliberately non-interactive shell.

It does not implement authenticated Gradio event execution.

A valid browser cookie does not authorize access to
private documents, queued events, or session state.

Never authorize operations using session_hash alone.

Do not broadly exempt:
    /ui/gradio_api/*
    /ui/file=*
    /ui/static/*
    /ui/*

Public asset directories must be verified to contain only
bundled, non-sensitive resources before production deployment.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from frontend.http_session import HTTPSessionCookies


class GradioSecurityGate:
    """
    Enforce an explicit allowlist for the mounted Gradio shell.

    Requests that cannot be authorized are denied by default.
    """

    def __init__(
        self,
        cookies: HTTPSessionCookies,
        *,
        mount_path: str = "/ui",
    ) -> None:
        if not isinstance(mount_path, str):
            raise TypeError("mount_path must be a string.")

        if not mount_path.startswith("/"):
            raise ValueError(
                "mount_path must start with '/'."
            )

        normalized_path = mount_path.rstrip("/")

        if not normalized_path:
            raise ValueError(
                "Gradio cannot be mounted at the root path "
                "using this security gate."
            )

        self._cookies = cookies
        self._mount_path = normalized_path

        # Exact public shell resources.
        self._allowed_exact_paths = frozenset(
            {
                self._mount_path,
                self._mount_path + "/",
                self._mount_path + "/theme.css",
            }
        )

        # Gradio's bundled frontend assets.
        self._asset_prefix = (
            self._mount_path + "/assets/"
        )

        # Restrict static access to bundled font resources.
        # Do not permit the entire /static/ namespace.
        self._font_prefix = (
            self._mount_path + "/static/fonts/"
        )

    def _is_gradio_path(self, path: str) -> bool:
        """Check whether a request targets mounted Gradio."""

        return (
            path == self._mount_path
            or path.startswith(self._mount_path + "/")
        )

    @staticmethod
    def _has_safe_path_segments(
        relative_path: str,
    ) -> bool:
        """
        Reject empty, dot, and traversal path segments.

        The ASGI server must also normalize request paths.
        """

        if not relative_path:
            return False

        segments = relative_path.split("/")

        return not any(
            segment in ("", ".", "..")
            for segment in segments
        )

    def _is_allowed_public_resource(
        self,
        path: str,
    ) -> bool:
        """
        Check the narrow public-resource allowlist.

        Query parameters do not affect authorization.
        """

        if path in self._allowed_exact_paths:
            return True

        # Public bundled assets, such as Gradio JavaScript
        # and CSS files.
        if path.startswith(self._asset_prefix):
            relative_path = path[
                len(self._asset_prefix):
            ]

            return self._has_safe_path_segments(
                relative_path
            )

        # Gradio's bundled font files only.
        if path.startswith(self._font_prefix):
            relative_path = path[
                len(self._font_prefix):
            ]

            if not self._has_safe_path_segments(
                relative_path
            ):
                return False

            return relative_path.lower().endswith(
                (".woff", ".woff2")
            )

        # Unknown resources fail closed.
        return False

    async def authorize(
        self,
        request: Request,
    ) -> Response | None:
        """
        Authorize a request to the restricted Gradio shell.

        Returns
        -------
        None
            Request may continue to Gradio.

        Response
            Request is denied with HTTP 401 or 403.
        """

        path = request.url.path

        # Other application routes are handled separately.
        if not self._is_gradio_path(path):
            return None

        # Validate the browser cookie against the
        # server-side identity registry.
        identity = self._cookies.read_identity(request)

        if identity is None:
            return JSONResponse(
                {
                    "detail": "Browser session required."
                },
                status_code=401,
            )

        # The restricted shell is read-only.
        if request.method not in ("GET", "HEAD"):
            return JSONResponse(
                {
                    "detail": "Operation not permitted."
                },
                status_code=403,
            )

        # Only approved public resources are accessible.
        if self._is_allowed_public_resource(path):
            return None

        # Everything else fails closed.
        return JSONResponse(
            {
                "detail": (
                    "Gradio endpoint disabled pending "
                    "authorization integration."
                )
            },
            status_code=403,
        )