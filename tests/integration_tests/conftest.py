
"""
MODULE NAME
-----------
INTEGRATION TEST STORAGE SAFETY

PURPOSE
-------
Prevent integration tests from accidentally connecting to the
working PostgreSQL database or persistent ChromaDB directory.

ENVIRONMENT / CONFIGURATION
---------------------------
RUN_PHASE4_DB_TESTS=1 enables database-backed integration tests.

PostgreSQL test database:
    health_rag_migration_test

ChromaDB:
    An isolated pytest temporary directory.

DEPENDENCIES
------------
pytest
psycopg
chromadb
services.vector_store_service

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Automatically isolate ChromaDB.
2. Reject PostgreSQL connections to non-test databases.
3. Reject ChromaDB connections to non-test storage.
4. Disable the scheduled document cleanup worker.
5. Prevent accidental use of unqualified database connections.
6. Preserve the shared database safety fixture.

SECURITY NOTES
--------------
These guards apply to integration-test execution.

They do not protect an independently running API server,
external PostgreSQL clients, or module-import side effects
that occur before pytest fixtures initialize.

Do not remove the guards to make a failing test pass.
"""

import os
from pathlib import Path

import chromadb
import psycopg
import pytest

from psycopg.conninfo import conninfo_to_dict

from services.vector_store_service import (
    CHROMA_DB_PATH,
    get_chroma_db_path,
)


TEST_DATABASE_NAME = "health_rag_migration_test"


# =============================================================================
# AUTOMATIC STORAGE PROTECTION
# =============================================================================

@pytest.fixture(autouse=True)
def protect_integration_storage(
    monkeypatch,
    safe_test_chroma,
):
    """
    Protect storage access during every integration test.

    PostgreSQL connections must explicitly select the test DB.
    ChromaDB connections must use pytest's isolated directory.
    """
    test_chroma_path = safe_test_chroma.resolve()
    application_chroma_path = CHROMA_DB_PATH.resolve()

    monkeypatch.setenv(
        "ENABLE_DOCUMENT_CLEANUP",
        "false",
    )

    # The shared fixture must already have configured the
    # isolated ChromaDB directory.
    if get_chroma_db_path() != test_chroma_path:
        pytest.fail(
            "ChromaDB isolation was not initialized.",
            pytrace=False,
        )

    original_pg_connect = psycopg.connect
    original_chroma_client = chromadb.PersistentClient

    # -----------------------------------------------------------------
    # PostgreSQL connection guard
    # -----------------------------------------------------------------

    def guarded_pg_connect(*args, **kwargs):
        """
        Reject any PostgreSQL connection that does not explicitly
        target the dedicated integration-test database.
        """
        parameters = {}

        if args:
            parameters.update(conninfo_to_dict(args[0]))

        if kwargs.get("conninfo"):
            parameters.update(
                conninfo_to_dict(kwargs["conninfo"])
            )

        parameters.update(
            {
                key: value
                for key, value in kwargs.items()
                if key != "conninfo"
            }
        )

        database_name = (
            parameters.get("dbname")
            or parameters.get("database")
        )

        if database_name != TEST_DATABASE_NAME:
            raise RuntimeError(
                "Unsafe PostgreSQL connection blocked. "
                f"Requested database: {database_name!r}. "
                f"Required database: {TEST_DATABASE_NAME!r}."
            )

        return original_pg_connect(*args, **kwargs)

    # -----------------------------------------------------------------
    # ChromaDB connection guard
    # -----------------------------------------------------------------

    def guarded_chroma_client(*args, **kwargs):
        """
        Reject persistent ChromaDB clients pointing anywhere
        other than the isolated pytest directory.
        """
        configured_path = (
            args[0]
            if args
            else kwargs.get("path")
        )

        if configured_path is None:
            raise RuntimeError(
                "ChromaDB connection requires an explicit test path."
            )

        actual_path = Path(
            configured_path
        ).expanduser().resolve()

        if actual_path == application_chroma_path:
            raise RuntimeError(
                "Application ChromaDB storage access blocked."
            )

        if actual_path != test_chroma_path:
            raise RuntimeError(
                "ChromaDB client requested unexpected storage: "
                f"{actual_path}"
            )

        return original_chroma_client(*args, **kwargs)

    monkeypatch.setattr(
        psycopg,
        "connect",
        guarded_pg_connect,
    )

    monkeypatch.setattr(
        chromadb,
        "PersistentClient",
        guarded_chroma_client,
    )

    yield