
"""
Phase 4.2 — User registration integration tests.

PURPOSE
-------
Verify that the FastAPI registration endpoint correctly interacts
with the authentication service and PostgreSQL.

This test covers:
    1. Successful registration (HTTP 201).
    2. Safe API response fields.
    3. Argon2id password storage and verification.
    4. Duplicate-email rejection (HTTP 409).
    5. Email normalization.
    6. Invalid password rejection (HTTP 422).
    7. Invalid email rejection (HTTP 422).

All temporary accounts are created in the isolated test database
and removed during cleanup.
"""

from uuid import uuid4

import psycopg
import pytest

from fastapi.testclient import TestClient

from api.main import app
from services.auth_service import verify_password
from services.database_service import get_user_by_email


TEST_DATABASE_NAME = "health_rag_migration_test"
TEST_DATABASE_OWNER = "tasmiyasana"

VALID_TEST_PASSWORD = "SecurePassword2026!"


# Before running any test in this module, pytest executes the
# database safety checks defined in conftest.py.
pytestmark = pytest.mark.usefixtures("safe_test_database")


def test_complete_registration_workflow():
    """
    Exercise the complete HTTP registration and database workflow.

    The shared fixture has already verified that the application
    points to the isolated PostgreSQL test database.
    """

    client = TestClient(app)

    # Generate unique addresses so this test does not collide with
    # previously created accounts or concurrent development activity.
    email = f"phase42-{uuid4().hex}@example.com"

    uppercase_email = (
        f"PHASE42-{uuid4().hex.upper()}@EXAMPLE.COM"
    )

    normalized_email = uppercase_email.lower()

    # Keep a precise list of accounts created by this test.
    # Cleanup must never delete unrelated database records.
    emails_to_cleanup = [
        email,
        normalized_email,
    ]

    # Open the database-owner connection before inserting records.
    # This role can remove temporary test accounts afterward.
    with psycopg.connect(
        dbname=TEST_DATABASE_NAME,
        user=TEST_DATABASE_OWNER,
    ) as admin_connection:

        try:
            # ------------------------------------------------------
            # TEST 1: Successful registration
            # ------------------------------------------------------
            #
            # TestClient sends an HTTP request directly to FastAPI.
            # No separate Uvicorn server is required.

            response = client.post(
                "/auth/register",
                json={
                    "email": email,
                    "password": VALID_TEST_PASSWORD,
                },
            )

            assert response.status_code == 201, response.text

            registered_user = response.json()

            assert registered_user["email"] == email
            assert registered_user["user_id"]
            assert registered_user["created_at"]

            # ------------------------------------------------------
            # TEST 2: Sensitive information must not be returned
            # ------------------------------------------------------
            #
            # Passwords and password hashes must never be included
            # in the registration response.

            assert "password" not in registered_user
            assert "password_hash" not in registered_user

            # ------------------------------------------------------
            # TEST 3: Password storage and verification
            # ------------------------------------------------------
            #
            # Retrieve the account from PostgreSQL using the
            # application's existing database service.

            stored_user = get_user_by_email(email)

            assert stored_user is not None

            stored_hash = stored_user["password_hash"]

            # Argon2id hashes begin with this algorithm identifier.
            assert stored_hash.startswith("$argon2id$")

            # The original password must verify against the hash.
            assert verify_password(
                VALID_TEST_PASSWORD,
                stored_hash,
            ) is True

            # An incorrect password must fail verification.
            assert verify_password(
                "IncorrectPassword2026!",
                stored_hash,
            ) is False

            # ------------------------------------------------------
            # TEST 4: Duplicate email rejection
            # ------------------------------------------------------
            #
            # PostgreSQL enforces the unique email constraint.
            # The API converts that database error to HTTP 409.

            duplicate_response = client.post(
                "/auth/register",
                json={
                    "email": email,
                    "password": VALID_TEST_PASSWORD,
                },
            )

            assert duplicate_response.status_code == 409

            # ------------------------------------------------------
            # TEST 5: Email normalization
            # ------------------------------------------------------
            #
            # Registration converts uppercase email addresses
            # into lowercase before storing them.

            normalized_response = client.post(
                "/auth/register",
                json={
                    "email": uppercase_email,
                    "password": VALID_TEST_PASSWORD,
                },
            )

            assert normalized_response.status_code == 201

            assert (
                normalized_response.json()["email"]
                == normalized_email
            )

            # ------------------------------------------------------
            # TEST 6: Short password rejection
            # ------------------------------------------------------
            #
            # Pydantic rejects passwords shorter than 12 characters
            # before the registration service writes to PostgreSQL.

            short_password_response = client.post(
                "/auth/register",
                json={
                    "email": "invalid@example.com",
                    "password": "Short123!",
                },
            )

            assert short_password_response.status_code == 422

            # ------------------------------------------------------
            # TEST 7: Invalid email rejection
            # ------------------------------------------------------
            #
            # Pydantic EmailStr validates email syntax.

            invalid_email_response = client.post(
                "/auth/register",
                json={
                    "email": "not-an-email",
                    "password": VALID_TEST_PASSWORD,
                },
            )

            assert invalid_email_response.status_code == 422

        finally:
            # ------------------------------------------------------
            # CLEANUP: Remove temporary test accounts
            # ------------------------------------------------------
            #
            # finally executes even when an assertion fails.
            #
            # We delete only the two uniquely generated email
            # addresses, not all users in the database.

            with admin_connection.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM public.users
                    WHERE email = ANY(%s)
                    """,
                    (emails_to_cleanup,),
                )
