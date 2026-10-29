
"""
MODULE NAME
-----------
TEMPORARY DOCUMENT LIFECYCLE

PURPOSE
-------
Manage the lifecycle of temporary insurance-policy PDFs.

Coordinate document operations with cleanup so that an active
operation cannot lose its ChromaDB collection while processing.

ENVIRONMENT / CONFIGURATION
---------------------------
Uses the existing PostgreSQL and ChromaDB configuration.

ENABLE_DOCUMENT_CLEANUP:
    false by default.
    Set to true only after migration 007 and tests pass.

DOCUMENT_CLEANUP_INTERVAL_SECONDS:
    Defaults to 600 seconds (10 minutes).
    Minimum supported value is 60 seconds.

DEPENDENCIES
------------
services.database_service
services.document_operation_lock
services.session_database_service
services.vector_store_service

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Coordinate operations belonging to the same login session.
2. Verify session activity after acquiring the lock.
3. Keep locks held throughout retrieval and Gemini generation.
4. Find expired documents and revoked/expired sessions.
5. Skip cleanup when a session is busy.
6. Recheck cleanup eligibility before deletion.
7. Delete ChromaDB data before removing SQL metadata.
8. Support immediate cleanup after verified logout.
9. Schedule periodic cleanup.
10. Produce consistent audit logs.

SECURITY NOTES
--------------
Authentication and document ownership are separate requirements.

The API must obtain user_id and session_id from verified credentials.
The document service must still check ownership and expiration.

Never use a client-supplied session ID for cleanup authorization.

Legacy documents without ownership metadata are excluded.

Never log PDF contents, passwords, or refresh-token secrets.

This prototype should run with one API worker for the scheduler.
PostgreSQL advisory locks coordinate access across connections.
"""

import contextvars
import functools
import inspect
import logging
import os
import threading
import uuid

from services.database_service import get_db_connection
from services.document_operation_lock import (
    lock_document,
    try_lock_document,
)
from services.session_database_service import is_session_active
from services.vector_store_service import get_persistent_client


logger = logging.getLogger(__name__)

# Nested service functions must not acquire a second connection
# and block on their own outer operation.
_current_session = contextvars.ContextVar(
    "document_operation_session",
    default=None,
)

_scheduler_thread = None
_scheduler_stop = threading.Event()


# =============================================================================
# CONSISTENT AUDIT LOGGING
# =============================================================================

def audit(
    event: str,
    document_id: str | None,
    session_id: str | None,
    outcome: str,
) -> None:
    """Log lifecycle events without sensitive document content."""
    logger.info(
        "document_lifecycle "
        "event=%s document_id=%s session_id=%s outcome=%s",
        event,
        document_id or "-",
        session_id or "-",
        outcome,
    )


# =============================================================================
# SESSION-COORDINATED OPERATIONS
# =============================================================================

def session_operation(func):
    """
    Hold a session advisory lock throughout a document operation.

    The lock is acquired before the original document-service
    function runs.

    The original function remains responsible for verifying
    document ownership and expiration.

    Nested operations reuse the outer lock.
    """

    @functools.wraps(func)
    def wrapped(*args, **kwargs):
        bound = inspect.signature(func).bind(*args, **kwargs)

        session_id = bound.arguments.get("session_id")
        user_id = bound.arguments.get("user_id")

        if not session_id or not user_id:
            raise ValueError(
                "Verified document identity is required."
            )

        session_id = str(uuid.UUID(str(session_id)))

        # A nested retrieval or answering call is already protected
        # by its outer operation.
        if _current_session.get() == session_id:
            return func(*args, **kwargs)

        # Use the session UUID as the shared advisory-lock key.
        # Cleanup must acquire this exact same lock.
        with lock_document(session_id):

            # Check authentication again after waiting for the lock.
            if not is_session_active(
                session_id=session_id,
                user_id=user_id,
            ):
                raise FileNotFoundError("Document not found.")

            token = _current_session.set(session_id)

            try:
                result = func(*args, **kwargs)

                audit(
                    func.__name__,
                    None,
                    session_id,
                    "success",
                )

                return result

            except Exception:
                audit(
                    func.__name__,
                    None,
                    session_id,
                    "failed",
                )
                raise

            finally:
                _current_session.reset(token)

    return wrapped


# =============================================================================
# CLEANUP CANDIDATE DISCOVERY
# =============================================================================

def _candidate_query(
    session_id: str | None,
    limit: int,
) -> tuple[str, tuple]:
    """
    Build a query for expired or revoked-session documents.

    Legacy ownerless documents must not be selected.
    """
    query = """
        SELECT
            d.document_id,
            d.session_id,
            d.collection_name
        FROM public.documents d
        LEFT JOIN public.user_sessions s
            ON s.session_id = d.session_id
        WHERE d.user_id IS NOT NULL
          AND d.session_id IS NOT NULL
          AND (
              d.expires_at <= CURRENT_TIMESTAMP
              OR s.revoked_at IS NOT NULL
              OR s.expires_at <= CURRENT_TIMESTAMP
          )
    """

    parameters = []

    if session_id is not None:
        query += " AND d.session_id = %s"
        parameters.append(uuid.UUID(str(session_id)))

    query += " ORDER BY d.expires_at ASC LIMIT %s"
    parameters.append(limit)

    return query, tuple(parameters)


def _cleanup_candidates(
    session_id: str | None,
    limit: int,
) -> list[dict]:
    """Read eligible candidates without deleting anything."""
    query, parameters = _candidate_query(
        session_id,
        limit,
    )

    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, parameters)
            return cursor.fetchall()


# =============================================================================
# CLEANUP ELIGIBILITY RECHECK
# =============================================================================

def _recheck_candidate(
    document_id: str,
    session_id: str,
) -> dict | None:
    """
    Confirm cleanup eligibility after acquiring the session lock.

    A document whose expiry was extended must not be deleted.
    """
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    d.document_id,
                    d.collection_name
                FROM public.documents d
                LEFT JOIN public.user_sessions s
                    ON s.session_id = d.session_id
                WHERE d.document_id = %s
                  AND d.session_id = %s
                  AND d.user_id IS NOT NULL
                  AND (
                      d.expires_at <= CURRENT_TIMESTAMP
                      OR s.revoked_at IS NOT NULL
                      OR s.expires_at <= CURRENT_TIMESTAMP
                  )
                """,
                (
                    document_id,
                    uuid.UUID(str(session_id)),
                ),
            )

            return cursor.fetchone()


def _remove_metadata(
    document_id: str,
    session_id: str,
) -> bool:
    """
    Remove SQL metadata only when cleanup is still permitted.

    ChromaDB deletion must happen before calling this function.
    """
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM public.documents d
                USING public.user_sessions s
                WHERE d.document_id = %s
                  AND d.session_id = %s
                  AND d.session_id = s.session_id
                  AND d.user_id IS NOT NULL
                  AND (
                      d.expires_at <= CURRENT_TIMESTAMP
                      OR s.revoked_at IS NOT NULL
                      OR s.expires_at <= CURRENT_TIMESTAMP
                  )
                RETURNING d.document_id
                """,
                (
                    document_id,
                    uuid.UUID(str(session_id)),
                ),
            )

            return cursor.fetchone() is not None


# =============================================================================
# EXPIRED-DOCUMENT CLEANUP
# =============================================================================

def cleanup_expired_documents(
    session_id: str | None = None,
    limit: int = 100,
) -> dict[str, int]:
    """
    Delete eligible temporary documents without blocking active work.

    Returns counts of deleted, busy, and failed candidates.

    If ChromaDB deletion fails, retain SQL metadata so cleanup
    can retry during the next scheduled run.
    """
    if not 1 <= limit <= 1000:
        raise ValueError(
            "Cleanup limit must be between 1 and 1000."
        )

    statistics = {
        "deleted": 0,
        "busy": 0,
        "failed": 0,
    }

    candidates = _cleanup_candidates(
        session_id,
        limit,
    )

    for item in candidates:
        document_id = str(item["document_id"])
        owner_session_id = str(item["session_id"])

        try:
            # Do not wait for an active retrieval or Gemini request.
            with try_lock_document(owner_session_id) as acquired:

                if not acquired:
                    statistics["busy"] += 1

                    audit(
                        "cleanup",
                        document_id,
                        owner_session_id,
                        "busy",
                    )
                    continue

                # Expiry may have changed since candidate discovery.
                metadata = _recheck_candidate(
                    document_id,
                    owner_session_id,
                )

                if metadata is None:
                    continue

                client = get_persistent_client()
                collection_name = metadata["collection_name"]

                existing_names = {
                    collection.name
                    for collection in client.list_collections()
                }

                if collection_name in existing_names:
                    client.delete_collection(
                        name=collection_name
                    )

                # Delete SQL metadata only after ChromaDB succeeds.
                if _remove_metadata(
                    document_id,
                    owner_session_id,
                ):
                    statistics["deleted"] += 1

                    audit(
                        "cleanup",
                        document_id,
                        owner_session_id,
                        "deleted",
                    )

        except Exception:
            statistics["failed"] += 1

            logger.exception(
                "Document cleanup failed: document_id=%s",
                document_id,
            )

            audit(
                "cleanup",
                document_id,
                owner_session_id,
                "failed",
            )

    return statistics


# =============================================================================
# LOGOUT CLEANUP
# =============================================================================

def cleanup_logged_out_session(
    session_id: str,
) -> dict[str, int]:
    """
    Attempt immediate cleanup after verified session revocation.

    The caller must first verify the refresh token and revoke
    its corresponding login session.
    """
    verified_session_id = str(uuid.UUID(str(session_id)))

    return cleanup_expired_documents(
        session_id=verified_session_id,
        limit=1000,
    )


# =============================================================================
# BACKGROUND SCHEDULER
# =============================================================================

def _cleanup_interval() -> int:
    """Validate the configured cleanup interval."""
    interval = int(
        os.getenv(
            "DOCUMENT_CLEANUP_INTERVAL_SECONDS",
            "600",
        )
    )

    if interval < 60:
        raise ValueError(
            "DOCUMENT_CLEANUP_INTERVAL_SECONDS must be >= 60."
        )

    return interval


def _cleanup_worker() -> None:
    """Run cleanup periodically until application shutdown."""
    interval = _cleanup_interval()

    while not _scheduler_stop.wait(interval):
        try:
            statistics = cleanup_expired_documents()

            logger.info(
                "document_lifecycle "
                "event=scheduled_cleanup "
                "outcome=complete "
                "deleted=%d busy=%d failed=%d",
                statistics["deleted"],
                statistics["busy"],
                statistics["failed"],
            )

        except Exception:
            logger.exception(
                "Scheduled document cleanup failed."
            )


def start_cleanup_scheduler() -> None:
    """
    Start the cleanup thread only when explicitly enabled.

    The scheduler is disabled by default to protect existing
    development data until migration and tests are complete.
    """
    global _scheduler_thread

    enabled = os.getenv(
        "ENABLE_DOCUMENT_CLEANUP",
        "false",
    ).strip().lower()

    if enabled != "true":
        logger.info(
            "Document cleanup scheduler disabled."
        )
        return

    if (
        _scheduler_thread is not None
        and _scheduler_thread.is_alive()
    ):
        return

    _cleanup_interval()

    _scheduler_stop.clear()

    _scheduler_thread = threading.Thread(
        target=_cleanup_worker,
        name="document-cleanup",
        daemon=True,
    )

    _scheduler_thread.start()

    logger.info(
        "Document cleanup scheduler started."
    )


def stop_cleanup_scheduler() -> None:
    """Stop the background worker on graceful API shutdown."""
    _scheduler_stop.set()

    if _scheduler_thread is not None:
        _scheduler_thread.join(timeout=5)
