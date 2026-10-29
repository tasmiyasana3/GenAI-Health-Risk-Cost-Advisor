
"""
Phase 4.4.5 — Document route authentication tests.

Verify that every document endpoint requires the existing
server-side authentication dependency.

These tests do not connect to PostgreSQL or ChromaDB.
"""

import pytest
from fastapi.testclient import TestClient

from api.auth_dependencies import get_current_user
from api.main import app


EXPECTED_DOCUMENT_ROUTES = {
    ("POST", "/documents"),
    ("GET", "/documents"),
    ("POST", "/documents/ask"),
    ("GET", "/documents/{document_id}"),
    ("DELETE", "/documents/{document_id}"),
    ("POST", "/documents/{document_id}/ask"),
}


def _document_routes():
    """Return registered document API routes."""
    return [
        route
        for route in app.routes
        if getattr(route, "path", "").startswith("/documents")
    ]


def test_all_expected_document_routes_exist():
    """Ensure no existing document endpoint was removed."""
    actual = {
        (method, route.path)
        for route in _document_routes()
        for method in route.methods
    }

    assert actual == EXPECTED_DOCUMENT_ROUTES


@pytest.mark.parametrize(
    "method,path",
    sorted(EXPECTED_DOCUMENT_ROUTES),
)
def test_document_routes_require_verified_identity(method, path):
    """Each document route must depend on get_current_user."""
    route = next(
        (
            route
            for route in _document_routes()
            if route.path == path and method in route.methods
        ),
        None,
    )

    assert route is not None, f"Missing route: {method} {path}"

    dependency_calls = {
        dependency.call
        for dependency in route.dependant.dependencies
    }

    assert get_current_user in dependency_calls, (
        f"Authentication dependency missing: {method} {path}"
    )


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/documents"),
        ("POST", "/documents/ask"),
        ("GET", "/documents/00000000000000000000000000000001"),
        ("DELETE", "/documents/00000000000000000000000000000001"),
        ("POST", "/documents/00000000000000000000000000000001/ask"),
        ("POST", "/documents"),
    ],
)
def test_document_routes_reject_missing_token(method, path):
    """Unauthenticated requests must receive HTTP 401."""
    with TestClient(app) as client:
        response = client.request(
            method,
            path,
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required."


def test_health_endpoint_remains_public():
    """Existing health endpoint must remain accessible."""
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
