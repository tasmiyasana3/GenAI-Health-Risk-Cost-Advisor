
"""
MODULE NAME
-----------
DOCUMENT OPERATION LOCK

PURPOSE
-------
Coordinate operations that access the same indexed insurance PDF.

A document query, deletion, or cleanup operation must not modify
the same ChromaDB collection concurrently with another operation.

ENVIRONMENT / CONFIGURATION
---------------------------
Uses the existing PostgreSQL connection configuration.

No new environment variables, services, or paid infrastructure
are required.

PostgreSQL advisory locks are shared between application processes
connected to the same PostgreSQL database.

DEPENDENCIES
------------
hashlib
uuid
contextlib
services.database_service.get_db_connection

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Validate document IDs before acquiring locks.
2. Generate stable PostgreSQL advisory-lock keys.
3. Acquire locks in a consistent order.
4. Hold locks for the full protected operation.
5. Release locks when operations succeed or fail.
6. Avoid deadlocks caused by inconsistent multi-document ordering.

SECURITY NOTES
--------------
A lock is NOT an authorization check.

Callers must verify authenticated user/session ownership while
holding the relevant lock and before accessing ChromaDB.

Every operation touching a document collection must use the same
locking protocol, including expiration cleanup and logout cleanup.

Locks are released when their PostgreSQL connection closes.
"""

import hashlib
import logging
import uuid

from contextlib import contextmanager
from collections.abc import Generator, Sequence

from services.database_service import get_db_connection


logger = logging.getLogger(__name__)

# Domain separation prevents these advisory-lock keys from being
# confused with keys generated for unrelated application features.
LOCK_NAMESPACE = b"insurance-rag-document-v1:"


def document_lock_key(document_id: str) -> int:
    """
    Generate a stable signed 64-bit PostgreSQL advisory-lock key.

    Raises
    ------
    ValueError
        If document_id is not a valid UUID.
    """
    try:
        validated_id = uuid.UUID(str(document_id))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("Invalid document ID.") from error

    digest = hashlib.sha256(
        LOCK_NAMESPACE + validated_id.bytes
    ).digest()

    # PostgreSQL pg_advisory_lock(bigint) expects a signed
    # 64-bit integer.
    return int.from_bytes(
        digest[:8],
        byteorder="big",
        signed=True,
    )


def _normalized_document_ids(
    document_ids: Sequence[str],
) -> list[str]:
    """
    Normalize, deduplicate, and sort document identifiers.

    Consistent lock ordering prevents a common multi-document
    deadlock pattern.
    """
    if isinstance(document_ids, (str, bytes)):
        raise ValueError(
            "document_ids must be a sequence of UUID strings."
        )

    normalized = {
        str(uuid.UUID(str(document_id)))
        for document_id in document_ids
    }

    return sorted(normalized)


@contextmanager
def lock_documents(
    document_ids: Sequence[str],
) -> Generator[None, None, None]:
    """
    Hold PostgreSQL advisory locks throughout a document operation.

    Example
    -------
    with lock_documents([document_id]):
        # Verify ownership here.
        # Then perform ChromaDB work.

    Important
    ---------
    This function does not validate document ownership or expiry.

    PostgreSQL session-level advisory locks are deliberately used
    because the protected work may involve ChromaDB or Gemini
    outside a database transaction.

    Keep the connection open for the entire protected operation.
    """
    normalized_ids = _normalized_document_ids(document_ids)

    if not normalized_ids:
        raise ValueError(
            "At least one document ID is required."
        )

    keys = sorted({
        document_lock_key(document_id)
        for document_id in normalized_ids
    })

    with get_db_connection() as connection:
        acquired_keys: list[int] = []

        try:
            with connection.cursor() as cursor:
                for key in keys:
                    cursor.execute(
                        "SELECT pg_advisory_lock(%s)",
                        (key,),
                    )
                    acquired_keys.append(key)

            yield

        finally:
            # Release in reverse acquisition order.
            # If a connection is lost, PostgreSQL releases
            # its session-level locks automatically.
            with connection.cursor() as cursor:
                for key in reversed(acquired_keys):
                    cursor.execute(
                        "SELECT pg_advisory_unlock(%s)",
                        (key,),
                    )

            logger.debug(
                "Released document operation locks: count=%d",
                len(acquired_keys),
            )


@contextmanager
def lock_document(document_id: str) -> Generator[None, None, None]:
    """Convenience wrapper for a single-document operation."""
    with lock_documents([document_id]):
        yield


# =============================================================================
# PHASE 4.4.6 - NON-BLOCKING CLEANUP LOCK
# =============================================================================

@contextmanager
def try_lock_document(document_id: str) -> Generator[bool, None, None]:
    """
    Attempt to acquire a PostgreSQL advisory lock without waiting.

    PURPOSE
    -------
    Allow scheduled cleanup to skip a busy document/session rather
    than interrupting or waiting for an active operation.

    SECURITY NOTES
    --------------
    This lock must use the same key-generation function as
    lock_document(). Acquiring a lock does not authorize access.

    The caller must recheck cleanup eligibility after acquiring it.
    """
    key = document_lock_key(document_id)

    with get_db_connection() as connection:
        acquired = False

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_try_advisory_lock(%s) AS acquired",
                (key,),
            )
            result = cursor.fetchone()
            acquired = bool(result["acquired"])

        try:
            yield acquired

        finally:
            if acquired:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_advisory_unlock(%s)",
                        (key,),
                    )
