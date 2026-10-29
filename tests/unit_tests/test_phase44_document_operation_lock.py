
"""
MODULE NAME
-----------
PHASE 4.4 DOCUMENT OPERATION LOCK TESTS

PURPOSE
-------
Verify the document-locking interface without requiring
a live PostgreSQL database.

ENVIRONMENT / CONFIGURATION
---------------------------
Runs with pytest and the existing Python environment.

No database migrations or external services are required.

DEPENDENCIES
------------
pytest
unittest.mock
services.document_operation_lock

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Stable lock keys.
2. Invalid UUID rejection.
3. Duplicate document ID handling.
4. Consistent multi-document lock ordering.
5. Lock release after successful operations.
6. Lock release after exceptions.

SECURITY NOTES
--------------
These are isolated unit tests.

They do not prove database-level concurrency safety,
ownership enforcement, or safe cleanup integration.
Those require separate integration tests.
"""

import uuid

from unittest.mock import MagicMock

import pytest

import services.document_operation_lock as locks


DOCUMENT_A = str(uuid.UUID(int=1))
DOCUMENT_B = str(uuid.UUID(int=2))


def test_lock_key_is_stable():
    """The same UUID must always produce the same lock key."""
    first = locks.document_lock_key(DOCUMENT_A)
    second = locks.document_lock_key(DOCUMENT_A)

    assert first == second
    assert isinstance(first, int)
    assert -(2**63) <= first < 2**63


def test_different_documents_have_different_keys():
    """These two test documents must not share a lock key."""
    assert (
        locks.document_lock_key(DOCUMENT_A)
        != locks.document_lock_key(DOCUMENT_B)
    )


def test_invalid_document_id_is_rejected():
    """Malformed identifiers must not reach PostgreSQL."""
    with pytest.raises(ValueError):
        locks.document_lock_key("not-a-uuid")


def test_normalization_removes_duplicates():
    """Repeated document IDs must acquire only one lock."""
    result = locks._normalized_document_ids(
        [DOCUMENT_A, DOCUMENT_A, DOCUMENT_B]
    )

    assert len(result) == 2


def test_normalization_has_consistent_order():
    """Input order must not affect lock acquisition order."""
    first = locks._normalized_document_ids(
        [DOCUMENT_A, DOCUMENT_B]
    )
    second = locks._normalized_document_ids(
        [DOCUMENT_B, DOCUMENT_A]
    )

    assert first == second


def test_empty_document_list_is_rejected():
    """Empty operations must not acquire database connections."""
    with pytest.raises(ValueError):
        with locks.lock_documents([]):
            pass


def test_single_document_lock_is_released(monkeypatch):
    """A successful operation must release its advisory lock."""
    connection = MagicMock()
    cursor = MagicMock()

    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value = cursor

    monkeypatch.setattr(
        locks,
        "get_db_connection",
        lambda: connection,
    )

    with locks.lock_document(DOCUMENT_A):
        pass

    statements = [
        call.args[0]
        for call in cursor.execute.call_args_list
    ]

    assert statements == [
        "SELECT pg_advisory_lock(%s)",
        "SELECT pg_advisory_unlock(%s)",
    ]


def test_lock_released_after_exception(monkeypatch):
    """An application failure must not leave the lock held."""
    connection = MagicMock()
    cursor = MagicMock()

    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value = cursor

    monkeypatch.setattr(
        locks,
        "get_db_connection",
        lambda: connection,
    )

    with pytest.raises(RuntimeError):
        with locks.lock_document(DOCUMENT_A):
            raise RuntimeError("Simulated processing failure")

    statements = [
        call.args[0]
        for call in cursor.execute.call_args_list
    ]

    assert statements[-1] == (
        "SELECT pg_advisory_unlock(%s)"
    )
