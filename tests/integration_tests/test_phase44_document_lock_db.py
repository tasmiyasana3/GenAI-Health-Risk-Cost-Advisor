
"""
MODULE NAME
-----------
PHASE 4.4.6 POSTGRESQL LOCK INTEGRATION TEST

PURPOSE
-------
Verify advisory-lock exclusion across PostgreSQL connections.

ENVIRONMENT / CONFIGURATION
---------------------------
RUN_PHASE4_DB_TESTS=1 enables this test.

The test forces DB_NAME=health_rag_migration_test.

DEPENDENCIES
------------
pytest
PostgreSQL
services.database_service
services.document_operation_lock

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Confirm the isolated database is selected.
2. Acquire a session lock.
3. Verify another connection cannot acquire it.
4. Release the lock.
5. Verify another connection can acquire it afterward.

SECURITY NOTES
--------------
Never run destructive tests against health_rag_db.

This test performs no INSERT, UPDATE, or DELETE operations.
"""

import os
import uuid

import pytest



if os.getenv("RUN_PHASE4_DB_TESTS") != "1":
    pytest.skip(
        "Isolated database integration tests disabled.",
        allow_module_level=True,
    )


from services.database_service import get_db_connection
from services.document_operation_lock import (
    lock_document,
    try_lock_document,
)


def test_cross_connection_lock_exclusion(monkeypatch):
    """Cleanup must skip a lock held by another connection."""
    monkeypatch.setenv(
        "DB_NAME",
        "health_rag_migration_test",
    )

    # Verify database identity before performing the test.
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_database() AS name"
            )

            assert (
                cursor.fetchone()["name"]
                == "health_rag_migration_test"
            )

    session_id = str(uuid.uuid4())

    # One connection holds the lock.
    with lock_document(session_id):

        # A separate connection must not acquire it.
        with try_lock_document(session_id) as acquired:
            assert acquired is False

    # After release, another connection can acquire it.
    with try_lock_document(session_id) as acquired:
        assert acquired is True
