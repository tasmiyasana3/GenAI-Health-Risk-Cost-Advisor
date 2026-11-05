
"""
MODULE NAME
-----------
GRADIO SECURITY LIVE SMOKE TEST

PURPOSE
-------
Verify that the restricted Gradio frontend shell is accessible
while unapproved static resources and protected operations
remain blocked by the frontend security gate.

ENVIRONMENT / CONFIGURATION
---------------------------
Requires the secured frontend to be running locally.

FRONTEND_SMOKE_BASE_URL optionally overrides the default URL.

DEPENDENCIES
------------
httpx and Python standard library.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
- Anonymous browser bootstrap.
- Restricted Gradio shell access.
- Unapproved static JavaScript denial.
- Gradio queue execution denial.
- Gradio upload denial.
- Gradio file-serving denial.
- Gradio event execution denial.

SECURITY NOTES
--------------
- Uses an anonymous browser session.
- Does not require credentials.
- Does not call paid APIs.
- Does not upload or modify real documents.
- Uses only synthetic request data.
- Does not modify application configuration.
"""

from __future__ import annotations

import os

import httpx


BASE_URL = os.getenv(
    "FRONTEND_SMOKE_BASE_URL",
    "http://127.0.0.1:7860",
).rstrip("/")


def assert_status(
    response: httpx.Response,
    expected: int,
    description: str,
) -> None:
    """Check the HTTP status and print a useful test result."""

    actual = response.status_code

    assert actual == expected, (
        f"{description}: expected HTTP {expected}, "
        f"received HTTP {actual}."
    )

    print(f"PASS: {description} (HTTP {actual})")


def main() -> None:
    """Run the live Gradio security boundary checks."""

    print("\nPHASE 5.2.4 — GRADIO SECURITY SMOKE TEST")
    print("-" * 55)

    with httpx.Client(
        base_url=BASE_URL,
        follow_redirects=False,
        timeout=10.0,
        trust_env=False,
    ) as browser:

        # Establish a legitimate anonymous browser identity.
        bootstrap = browser.get("/")

        assert_status(
            bootstrap,
            303,
            "Anonymous browser bootstrap",
        )

        # The restricted Gradio shell must remain accessible.
        shell = browser.get("/ui/")

        assert_status(
            shell,
            200,
            "Restricted Gradio shell loads",
        )

        # This static resource is intentionally outside the
        # current security gate's approved resource list.
        static_resource = browser.get(
            "/ui/static/js/iframeResizer.contentWindow.min.js"
        )

        assert_status(
            static_resource,
            403,
            "Unapproved static JavaScript blocked",
        )

        # Gradio queue execution must remain unavailable.
        queue = browser.post(
            "/ui/gradio_api/queue/join",
            json={},
        )

        assert_status(
            queue,
            403,
            "Gradio queue execution blocked",
        )

        # Uploads must remain disabled until ownership
        # and authorization are implemented.
        upload = browser.post(
            "/ui/gradio_api/upload",
            files={
                "files": (
                    "synthetic_test.txt",
                    b"synthetic test content",
                )
            },
        )

        assert_status(
            upload,
            403,
            "Gradio upload blocked",
        )

        # File-serving routes must not bypass the gate.
        file_request = browser.get(
            "/ui/gradio_api/file=nonexistent.txt"
        )

        assert_status(
            file_request,
            403,
            "Gradio file-serving blocked",
        )

        # Unapproved event execution must remain disabled.
        event = browser.post(
            "/ui/gradio_api/call/predict",
            json={},
        )

        assert_status(
            event,
            403,
            "Gradio event execution blocked",
        )

    print("\nSUCCESS: All 7 Gradio security checks passed.")


if __name__ == "__main__":
    main()