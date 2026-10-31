
"""
MODULE NAME
-----------
PHASE 4.4.6A STORAGE CONNECTION GUARD TESTS

PURPOSE
-------
Verify that integration tests reject unsafe PostgreSQL and
ChromaDB connection requests.

ENVIRONMENT / CONFIGURATION
---------------------------
Uses the automatic fixtures in integration_tests/conftest.py.

DEPENDENCIES
------------
pytest
psycopg
chromadb
services.vector_store_service

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Reject the working PostgreSQL database.
2. Reject PostgreSQL connections without a database name.
3. Reject the application's ChromaDB directory.
4. Accept the isolated ChromaDB directory.

SECURITY NOTES
--------------
Unsafe connection requests must fail before a connection opens.
"""

import chromadb
import psycopg
import pytest

from services.vector_store_service import (
    CHROMA_DB_PATH,
    get_chroma_db_path,
)


def test_working_postgresql_database_is_blocked():
    with pytest.raises(
        RuntimeError,
        match="Unsafe PostgreSQL connection blocked",
    ):
        psycopg.connect(
            dbname="health_rag_db",
        )


def test_unqualified_postgresql_connection_is_blocked():
    with pytest.raises(
        RuntimeError,
        match="Unsafe PostgreSQL connection blocked",
    ):
        psycopg.connect()


def test_application_chroma_storage_is_blocked():
    with pytest.raises(
        RuntimeError,
        match="Application ChromaDB storage access blocked",
    ):
        chromadb.PersistentClient(
            path=str(CHROMA_DB_PATH)
        )


def test_isolated_chroma_storage_is_allowed():
    client = chromadb.PersistentClient(
        path=str(get_chroma_db_path())
    )

    assert client is not None
