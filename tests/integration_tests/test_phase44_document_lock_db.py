
"""
MODULE NAME
-----------
PHASE 4.4.6 POSTGRESQL DOCUMENT LOCK INTEGRATION TEST

PURPOSE
-------
Verify that PostgreSQL advisory locks prevent concurrent
operations on the same document or session identifier.

ENVIRONMENT / CONFIGURATION
---------------------------
RUN_PHASE4_DB_TESTS=1:
    Enables PostgreSQL integration testing.

The shared safe_test_database fixture verifies that the
application is connected to health_rag_migration_test.

DEPENDENCIES
------------
pytest
services.database_service
services.document_operation_lock

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Verify that the isolated PostgreSQL test database is used.
2. Acquire an advisory lock on one connection.
3. Confirm another connection cannot acquire that lock.
4. Release the original lock.
5. Confirm another connection can acquire it afterward.

SECURITY NOTES
--------------
Never use the working health_rag_db database for this test.

This test does not insert, update, or delete PostgreSQL rows.

The safe_test_database fixture must complete successfully
before any advisory-lock operation begins.
"""

import uuid

import pytest

from services.database_service import get_db_connection

from services.document_operation_lock import (
    lock_document,
    try_lock_document,
)


# =============================================================================
# SHARED DATABASE SAFETY
# =============================================================================

pytestmark = pytest.mark.usefixtures(
    "safe_test_database"
)


# =============================================================================
# CROSS-CONNECTION LOCK EXCLUSION
# =============================================================================

def test_cross_connection_lock_exclusion():
    """
    Verify that another PostgreSQL connection cannot acquire
    a lock while it is held by an active operation.

    Once released, the lock must become available again.
    """
    # The shared fixture has already selected and verified
    # the isolated PostgreSQL database.
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_database() AS database_name"
            )

            database_name = cursor.fetchone()["database_name"]

    assert database_name == "health_rag_migration_test"

    # Use a unique identifier so this test cannot collide
    # with another document or session lock.
    session_id = str(uuid.uuid4())

    # STEP 1: Acquire the lock on the first connection.
    with lock_document(session_id):

        # STEP 2: A second connection must not acquire it.
        with try_lock_document(session_id) as acquired:
            assert acquired is False

    # STEP 3: The first connection has released the lock.
    # A second connection should now acquire it successfully.
    with try_lock_document(session_id) as acquired:
        assert acquired is True
