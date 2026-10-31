
"""
MODULE NAME
-----------
SHARED PYTEST CONFIGURATION

PURPOSE
-------
Provide verified, isolated storage for integration tests.

ENVIRONMENT / CONFIGURATION
---------------------------
RUN_PHASE4_DB_TESTS=1:
    Enables PostgreSQL-backed integration tests.

PostgreSQL application database:
    health_rag_db

PostgreSQL integration-test database:
    health_rag_migration_test

ChromaDB application storage:
    storage/chroma_db/

ChromaDB test storage:
    A temporary directory managed by pytest.

DEPENDENCIES
------------
pytest
psycopg
services.database_service
services.vector_store_service

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Verify the PostgreSQL test database.
2. Verify database-owner cleanup permissions.
3. Create an isolated persistent ChromaDB directory.
4. Confirm the ChromaDB client uses that directory.
5. Reject unsafe storage paths.
6. Restore environment settings after testing.

SECURITY NOTES
--------------
Never run destructive tests against health_rag_db or the
application's normal ChromaDB directory.

The ChromaDB fixture is explicitly requested by tests.
Document integration tests must use both storage fixtures.

The ChromaDB fixture does not start the cleanup scheduler.
"""

import os

from pathlib import Path

import psycopg
import pytest

from services.database_service import get_db_connection
from services.vector_store_service import (
    CHROMA_DB_PATH,
    get_chroma_db_path,
    get_persistent_client,
)


WORKING_DATABASE_NAME = "health_rag_db"
TEST_DATABASE_NAME = "health_rag_migration_test"

DATABASE_TEST_FLAG = "RUN_PHASE4_DB_TESTS"
TEST_DATABASE_OWNER = "tasmiyasana"


# =============================================================================
# POSTGRESQL TEST ISOLATION
# =============================================================================

@pytest.fixture
def safe_test_database(monkeypatch):
    """
    Select and verify the isolated PostgreSQL test database.

    Database tests require explicit opt-in. Both application and
    cleanup-owner connections are verified before test execution.
    """
    if os.getenv(DATABASE_TEST_FLAG) != "1":
        pytest.skip(
            "Database integration tests are disabled. "
            "Set RUN_PHASE4_DB_TESTS=1 to enable them."
        )

    monkeypatch.setenv(
        "DB_NAME",
        TEST_DATABASE_NAME,
    )

    # Verify the database used by the application connection.
    with get_db_connection() as application_connection:
        with application_connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_database() AS database_name"
            )
            actual_database_name = cursor.fetchone()["database_name"]

    if actual_database_name != TEST_DATABASE_NAME:
        pytest.fail(
            "Database safety verification failed.\n"
            f"Actual database: {actual_database_name!r}\n"
            f"Expected database: {TEST_DATABASE_NAME!r}",
            pytrace=False,
        )

    # Verify the separate owner connection used for test cleanup.
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

            owner_database_name, can_delete_users = cursor.fetchone()

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

    yield


# =============================================================================
# CHROMADB TEST ISOLATION
# =============================================================================

@pytest.fixture
def safe_test_chroma(monkeypatch, tmp_path):
    """
    Provide a separate persistent ChromaDB directory for one test.

    Yields
    ------
    pathlib.Path
        The verified temporary ChromaDB storage directory.

    Notes
    -----
    This fixture does not connect to PostgreSQL.

    It verifies the path configured in the application and the
    actual persistent directory reported by the ChromaDB client.
    """
    application_path = CHROMA_DB_PATH.resolve()
    project_root = application_path.parents[1]

    test_path = (tmp_path / "chroma_db").resolve()

    # The test database must not overlap the application directory.
    if (
        test_path == application_path
        or test_path in application_path.parents
        or application_path in test_path.parents
    ):
        pytest.fail(
            "ChromaDB test path overlaps application storage.",
            pytrace=False,
        )

    # Do not create test storage anywhere inside the project.
    if test_path == project_root or project_root in test_path.parents:
        pytest.fail(
            "ChromaDB test storage must be outside the project.",
            pytrace=False,
        )

    monkeypatch.setenv(
        "CHROMA_DB_PATH",
        str(test_path),
    )

    # Verify the application's path resolution.
    configured_path = get_chroma_db_path()

    if configured_path != test_path:
        pytest.fail(
            "ChromaDB path override was not applied.",
            pytrace=False,
        )

    # Verify the real client configuration, not only the env variable.
    client = get_persistent_client()
    actual_path = Path(
        client.get_settings().persist_directory
    ).expanduser().resolve()

    if actual_path != test_path:
        pytest.fail(
            "ChromaDB client connected to an unexpected directory.\n"
            f"Actual: {actual_path}\n"
            f"Expected: {test_path}",
            pytrace=False,
        )

    yield test_path

    # pytest cleans up temporary directories.
    # monkeypatch restores CHROMA_DB_PATH automatically.
