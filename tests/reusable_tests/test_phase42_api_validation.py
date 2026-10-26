
"""Phase 4.2: Registration endpoint and input validation tests."""

from fastapi.testclient import TestClient

from api.main import app


client = TestClient(app)


def test_registration_endpoint_exists():
    """Verify registration is included in the OpenAPI schema."""
    schema = app.openapi()

    assert "/auth/register" in schema["paths"]
    assert "post" in schema["paths"]["/auth/register"]


def test_invalid_email_returns_422():
    response = client.post(
        "/auth/register",
        json={
            "email": "invalid-email",
            "password": "SecurePassword2026!",
        },
    )

    assert response.status_code == 422


def test_short_password_returns_422():
    response = client.post(
        "/auth/register",
        json={
            "email": "test@example.com",
            "password": "Short123!",
        },
    )

    assert response.status_code == 422


def test_missing_password_returns_422():
    response = client.post(
        "/auth/register",
        json={
            "email": "test@example.com",
        },
    )

    assert response.status_code == 422


def test_missing_email_returns_422():
    response = client.post(
        "/auth/register",
        json={
            "password": "SecurePassword2026!",
        },
    )

    assert response.status_code == 422
