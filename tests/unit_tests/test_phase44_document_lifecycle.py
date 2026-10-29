
"""
MODULE NAME
-----------
PHASE 4.4.6 DOCUMENT LIFECYCLE UNIT TESTS

PURPOSE
-------
Verify lifecycle coordination without a live database.

ENVIRONMENT / CONFIGURATION
---------------------------
Uses pytest and monkeypatch.
No PostgreSQL or ChromaDB connection is required.

DEPENDENCIES
------------
pytest
unittest.mock
services.document_lifecycle

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Active session verification.
2. Revoked session rejection.
3. Nested locking.
4. Busy cleanup behavior.
5. Expiry rechecking.
6. Chroma-before-SQL deletion.
7. Cleanup failure handling.
8. Scheduler disabled by default.
9. Cleanup limit validation.

SECURITY NOTES
--------------
Mocks isolate these tests from real user documents.
Database-level locking is tested separately.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

import services.document_lifecycle as lifecycle


TEST_SESSION_ID = "00000000-0000-0000-0000-000000000001"


@contextmanager
def fake_lock(session_id):
    """Simulate acquiring an operation lock."""
    yield


@contextmanager
def busy_lock(session_id):
    """Simulate a document session currently in use."""
    yield False


@contextmanager
def available_lock(session_id):
    """Simulate successful cleanup-lock acquisition."""
    yield True


def fake_candidates(*args):
    """Return one eligible cleanup candidate."""
    return [
        {
            "document_id": "test-document",
            "session_id": TEST_SESSION_ID,
        }
    ]


def test_session_lock_authorizes_before_operation(monkeypatch):
    """An active session can execute its document operation."""
    monkeypatch.setattr(
        lifecycle,
        "lock_document",
        fake_lock,
    )

    monkeypatch.setattr(
        lifecycle,
        "is_session_active",
        lambda **kwargs: True,
    )

    wrapped = lifecycle.session_operation(
        lambda user_id, session_id: "ok"
    )

    assert wrapped("test-user", TEST_SESSION_ID) == "ok"


def test_revoked_session_rejected(monkeypatch):
    """An inactive session cannot execute a document operation."""
    monkeypatch.setattr(
        lifecycle,
        "lock_document",
        fake_lock,
    )

    monkeypatch.setattr(
        lifecycle,
        "is_session_active",
        lambda **kwargs: False,
    )

    wrapped = lifecycle.session_operation(
        lambda user_id, session_id: "never"
    )

    with pytest.raises(FileNotFoundError):
        wrapped("test-user", TEST_SESSION_ID)


def test_nested_operations_reuse_session_lock(monkeypatch):
    """Nested retrieval must not acquire another session lock."""
    acquisitions = []

    @contextmanager
    def counting_lock(session_id):
        acquisitions.append(session_id)
        yield

    monkeypatch.setattr(
        lifecycle,
        "lock_document",
        counting_lock,
    )

    monkeypatch.setattr(
        lifecycle,
        "is_session_active",
        lambda **kwargs: True,
    )

    inner = lifecycle.session_operation(
        lambda user_id, session_id: "ok"
    )

    outer = lifecycle.session_operation(
        lambda user_id, session_id: inner(
            user_id,
            session_id,
        )
    )

    assert outer("test-user", TEST_SESSION_ID) == "ok"
    assert len(acquisitions) == 1


def test_cleanup_skips_busy_session(monkeypatch):
    """Cleanup must not delete data used by an active operation."""
    monkeypatch.setattr(
        lifecycle,
        "_cleanup_candidates",
        fake_candidates,
    )

    monkeypatch.setattr(
        lifecycle,
        "try_lock_document",
        busy_lock,
    )

    assert lifecycle.cleanup_expired_documents() == {
        "deleted": 0,
        "busy": 1,
        "failed": 0,
    }


def test_cleanup_rechecks_eligibility(monkeypatch):
    """An extended document expiry must prevent deletion."""
    monkeypatch.setattr(
        lifecycle,
        "_cleanup_candidates",
        fake_candidates,
    )

    monkeypatch.setattr(
        lifecycle,
        "try_lock_document",
        available_lock,
    )

    monkeypatch.setattr(
        lifecycle,
        "_recheck_candidate",
        lambda *args: None,
    )

    monkeypatch.setattr(
        lifecycle,
        "get_persistent_client",
        lambda: pytest.fail(
            "ChromaDB must not be accessed."
        ),
    )

    result = lifecycle.cleanup_expired_documents()

    assert result["deleted"] == 0


def test_cleanup_deletes_collection_before_metadata(monkeypatch):
    """ChromaDB deletion must precede SQL metadata deletion."""
    deletion_order = []

    monkeypatch.setattr(
        lifecycle,
        "_cleanup_candidates",
        fake_candidates,
    )

    monkeypatch.setattr(
        lifecycle,
        "try_lock_document",
        available_lock,
    )

    monkeypatch.setattr(
        lifecycle,
        "_recheck_candidate",
        lambda *args: {
            "collection_name": "test-collection",
        },
    )

    client = MagicMock()

    collection = MagicMock()
    collection.name = "test-collection"

    client.list_collections.return_value = [collection]

    client.delete_collection.side_effect = (
        lambda **kwargs: deletion_order.append("chroma")
    )

    monkeypatch.setattr(
        lifecycle,
        "get_persistent_client",
        lambda: client,
    )

    monkeypatch.setattr(
        lifecycle,
        "_remove_metadata",
        lambda *args: (
            deletion_order.append("sql") or True
        ),
    )

    result = lifecycle.cleanup_expired_documents()

    assert result["deleted"] == 1
    assert deletion_order == ["chroma", "sql"]


def test_cleanup_failure_retains_metadata(monkeypatch):
    """Failed ChromaDB deletion must not remove SQL metadata."""
    monkeypatch.setattr(
        lifecycle,
        "_cleanup_candidates",
        fake_candidates,
    )

    monkeypatch.setattr(
        lifecycle,
        "try_lock_document",
        available_lock,
    )

    monkeypatch.setattr(
        lifecycle,
        "_recheck_candidate",
        lambda *args: {
            "collection_name": "test-collection",
        },
    )

    client = MagicMock()

    client.list_collections.side_effect = RuntimeError(
        "Simulated ChromaDB failure"
    )

    monkeypatch.setattr(
        lifecycle,
        "get_persistent_client",
        lambda: client,
    )

    monkeypatch.setattr(
        lifecycle,
        "_remove_metadata",
        lambda *args: pytest.fail(
            "SQL metadata must not be deleted."
        ),
    )

    result = lifecycle.cleanup_expired_documents()

    assert result["failed"] == 1


def test_scheduler_disabled_by_default(monkeypatch):
    """Cleanup must not start without explicit configuration."""
    monkeypatch.delenv(
        "ENABLE_DOCUMENT_CLEANUP",
        raising=False,
    )

    lifecycle.start_cleanup_scheduler()

    assert (
        lifecycle._scheduler_thread is None
        or not lifecycle._scheduler_thread.is_alive()
    )


def test_cleanup_limit_validated():
    """Reject invalid cleanup batch sizes."""
    with pytest.raises(ValueError):
        lifecycle.cleanup_expired_documents(limit=0)
