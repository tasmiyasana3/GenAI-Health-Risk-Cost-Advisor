
"""
Shared pytest configuration for database integration tests.

PURPOSE
-------
This module ensures that database integration tests use the
isolated PostgreSQL testing database rather than the working
application database.

The normal application uses:
    health_rag_db

The integration tests use:
    health_rag_migration_test

Pytest automatically discovers this conftest.py file.

Developers do not need to import this module or change .env
before running database integration tests.

DATABASE TESTING RULES
----------------------
1. Database tests run only when RUN_PHASE4_DB_TESTS=1.
2. The fixture temporarily selects the isolated test database.
3. PostgreSQL must confirm that the actual connection reaches
   the correct database.
4. The database-owner connection used for cleanup is also checked.
5. Environment changes are automatically restored after testing.
"""

import os

import psycopg
import pytest

from services.database_service import get_db_connection


# The database containing existing application records.
# This must never be used for integration test writes.
WORKING_DATABASE_NAME = "health_rag_db"

# The isolated database created for migration and authentication tests.
TEST_DATABASE_NAME = "health_rag_migration_test"

# Explicit opt-in required for tests that access PostgreSQL.
DATABASE_TEST_FLAG = "RUN_PHASE4_DB_TESTS"

# Local PostgreSQL role used for cleaning up temporary test accounts.
TEST_DATABASE_OWNER = "tasmiyasana"


@pytest.fixture
def safe_test_database(monkeypatch):
    """
    Prepare and verify an isolated PostgreSQL test environment.

    Parameters
    ----------
    monkeypatch:
        A built-in pytest fixture that temporarily changes
        environment variables.

    Yields
    ------
    None
        Allows the requesting test to execute after safety checks.

    Notes
    -----
    This fixture runs before database integration tests.

    It automatically selects the test database without changing
    the project's .env file permanently.
    """

    # --------------------------------------------------------------
    # STEP 1: Check whether database testing is enabled.
    # --------------------------------------------------------------
    #
    # Running "python -m pytest -q" should not automatically
    # execute tests that create or modify PostgreSQL records.
    #
    # Database tests require explicit developer permission.

    database_tests_enabled = (
        os.getenv(DATABASE_TEST_FLAG) == "1"
    )

    if not database_tests_enabled:
        pytest.skip(
            "Database integration tests are disabled. "
            "Set RUN_PHASE4_DB_TESTS=1 to enable them."
        )

    # --------------------------------------------------------------
    # STEP 2: Temporarily select the test database.
    # --------------------------------------------------------------
    #
    # The project's .env may contain:
    #
    #     DB_NAME=health_rag_db
    #
    # That is correct for the normal application.
    #
    # During integration testing, we temporarily override DB_NAME
    # so the database service connects to our isolated test DB.
    #
    # monkeypatch automatically restores the previous value after
    # the test finishes.

    monkeypatch.setenv(
        "DB_NAME",
        TEST_DATABASE_NAME,
    )

    # --------------------------------------------------------------
    # STEP 3: Verify the actual application database connection.
    # --------------------------------------------------------------
    #
    # Setting an environment variable alone is not enough.
    #
    # We ask PostgreSQL which database was actually selected.
    # If the database service ignores DB_NAME or is misconfigured,
    # this check should catch the problem.

    with get_db_connection() as application_connection:

        with application_connection.cursor() as cursor:

            cursor.execute(
                "SELECT current_database() AS database_name"
            )

            database_result = cursor.fetchone()

            actual_database_name = database_result["database_name"]

    if actual_database_name != TEST_DATABASE_NAME:
        pytest.fail(
            "Database safety verification failed.\n"
            f"Actual database: {actual_database_name!r}\n"
            f"Expected database: {TEST_DATABASE_NAME!r}",
            pytrace=False,
        )

    # --------------------------------------------------------------
    # STEP 4: Verify the database-owner cleanup connection.
    # --------------------------------------------------------------
    #
    # The application role health_rag_app has SELECT and INSERT
    # permissions, but intentionally does not have DELETE access
    # to the users table.
    #
    # Test cleanup uses the local database-owner role instead.
    #
    # We verify both:
    #   - Which database the owner reached.
    #   - Whether the owner can delete temporary test users.

    with psycopg.connect(
        dbname=TEST_DATABASE_NAME,
        user=TEST_DATABASE_OWNER,
    ) as owner_connection:

        with owner_connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    current_database() AS database_name,
                    has_table_privilege(
                        current_user,
                        'public.users',
                        'DELETE'
                    ) AS can_delete_users
                """
            )

            owner_database_name, can_delete_users = (
                cursor.fetchone()
            )

    if owner_database_name != TEST_DATABASE_NAME:
        pytest.fail(
            "Test cleanup connection reached an unexpected database.",
            pytrace=False,
        )

    if not can_delete_users:
        pytest.fail(
            "Test database owner cannot delete temporary users.",
            pytrace=False,
        )

    # --------------------------------------------------------------
    # STEP 5: Allow the integration test to run.
    # --------------------------------------------------------------
    #
    # All database safety checks have passed.
    #
    # The yield statement hands control back to pytest.
    # The actual test now runs.
    #
    # After the test, monkeypatch restores DB_NAME automatically.

    yield
