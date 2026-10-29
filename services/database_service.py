
"""
MODULE NAME
-----------
DATABASE SERVICE

PURPOSE
-------
Manage PostgreSQL connections, user accounts, and temporary
insurance-policy document metadata.

ENVIRONMENT / CONFIGURATION
---------------------------
Uses existing DB_HOST, DB_PORT, DB_NAME, DB_USER and DB_PASSWORD
environment variables.

DEPENDENCIES
------------
psycopg, python-dotenv, PostgreSQL migrations 001-007.

RESPONSIBILITIES
----------------
1. Preserve existing user registration and lookup operations.
2. Register documents for an authenticated user and session.
3. Restrict document operations to their owner and session.
4. Track document activity and expiration.
5. Keep legacy unassigned documents inaccessible.

SECURITY NOTES
--------------
user_id and session_id must come from the verified authentication
dependency, never from untrusted client-supplied values.

Expired documents are excluded from normal document access.
Physical cleanup is implemented separately.
"""

import os
from datetime import timedelta
from uuid import UUID, uuid4

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row


load_dotenv()

DOCUMENT_INACTIVITY_MINUTES = 30

DOCUMENT_COLUMNS = """
    document_id,
    filename,
    collection_name,
    status,
    uploaded_at,
    user_id,
    session_id,
    last_activity_at,
    expires_at
"""


# =============================================================================
# DATABASE CONNECTION
# =============================================================================

def get_db_connection():
    """Create a PostgreSQL connection using existing configuration."""
    return psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        connect_timeout=5,
        row_factory=dict_row,
    )


# =============================================================================
# INPUT VALIDATION
# =============================================================================

def _validate_uuid(value: str, field_name: str) -> UUID:
    """Validate an authenticated identity identifier."""
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError(
            f"{field_name} must be a valid UUID."
        ) from error


def _validate_document_id(document_id: str) -> str:
    """Require a nonempty document identifier."""
    if not isinstance(document_id, str) or not document_id.strip():
        raise ValueError("document_id must be a nonempty string.")

    return document_id


def _validate_owner(user_id: str, session_id: str) -> tuple[UUID, UUID]:
    """Validate the identity supplied by the trusted service layer."""
    return (
        _validate_uuid(user_id, "user_id"),
        _validate_uuid(session_id, "session_id"),
    )


# =============================================================================
# DOCUMENT REGISTRATION
# =============================================================================

def register_document(
    document_id: str,
    filename: str,
    collection_name: str,
    user_id: str,
    session_id: str,
) -> None:
    """Register a temporary document for an active login session."""
    validated_document_id = _validate_document_id(document_id)
    owner_id, owner_session_id = _validate_owner(user_id, session_id)

    query = """
        INSERT INTO public.documents (
            document_id,
            filename,
            collection_name,
            user_id,
            session_id,
            last_activity_at,
            expires_at
        )
        SELECT
            %s, %s, %s, %s, %s,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP + INTERVAL '30 minutes'
        WHERE EXISTS (
            SELECT 1
            FROM public.user_sessions
            WHERE session_id = %s
              AND user_id = %s
              AND revoked_at IS NULL
              AND expires_at > CURRENT_TIMESTAMP
        )
        RETURNING document_id
    """

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                query,
                (
                    validated_document_id,
                    filename,
                    collection_name,
                    owner_id,
                    owner_session_id,
                    owner_session_id,
                    owner_id,
                ),
            )

            if cursor.fetchone() is None:
                raise ValueError(
                    "Cannot register a document for an inactive session."
                )


# =============================================================================
# DOCUMENT RETRIEVAL
# =============================================================================

def get_document(
    document_id: str,
    user_id: str,
    session_id: str,
) -> dict | None:
    """Return an unexpired document belonging to this session."""
    validated_document_id = _validate_document_id(document_id)
    owner_id, owner_session_id = _validate_owner(user_id, session_id)

    query = f"""
        SELECT {DOCUMENT_COLUMNS}
        FROM public.documents
        WHERE document_id = %s
          AND user_id = %s
          AND session_id = %s
          AND expires_at > CURRENT_TIMESTAMP
          AND EXISTS (
              SELECT 1
              FROM public.user_sessions
              WHERE session_id = %s
                AND user_id = %s
                AND revoked_at IS NULL
                AND expires_at > CURRENT_TIMESTAMP
          )
    """

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                query,
                (
                    validated_document_id,
                    owner_id,
                    owner_session_id,
                    owner_session_id,
                    owner_id,
                ),
            )
            return cursor.fetchone()


def list_documents(
    user_id: str,
    session_id: str,
) -> list[dict]:
    """List only unexpired documents from this active session."""
    owner_id, owner_session_id = _validate_owner(user_id, session_id)

    query = f"""
        SELECT {DOCUMENT_COLUMNS}
        FROM public.documents
        WHERE user_id = %s
          AND session_id = %s
          AND expires_at > CURRENT_TIMESTAMP
          AND EXISTS (
              SELECT 1
              FROM public.user_sessions
              WHERE session_id = %s
                AND user_id = %s
                AND revoked_at IS NULL
                AND expires_at > CURRENT_TIMESTAMP
          )
        ORDER BY uploaded_at DESC
    """

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                query,
                (
                    owner_id,
                    owner_session_id,
                    owner_session_id,
                    owner_id,
                ),
            )
            return cursor.fetchall()


# =============================================================================
# DOCUMENT STATUS
# =============================================================================

def update_document_status(
    document_id: str,
    status: str,
    user_id: str,
    session_id: str,
) -> None:
    """Update a document status only for its owning session."""
    allowed_statuses = {"processing", "ready", "failed"}

    if status not in allowed_statuses:
        raise ValueError(f"Invalid document status: {status}")

    validated_document_id = _validate_document_id(document_id)
    owner_id, owner_session_id = _validate_owner(user_id, session_id)

    query = """
        UPDATE public.documents
        SET status = %s
        WHERE document_id = %s
          AND user_id = %s
          AND session_id = %s
        RETURNING document_id
    """

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                query,
                (
                    status,
                    validated_document_id,
                    owner_id,
                    owner_session_id,
                ),
            )

            if cursor.fetchone() is None:
                raise ValueError("Document not found.")


# =============================================================================
# DOCUMENT ACTIVITY
# =============================================================================

def touch_document(
    document_id: str,
    user_id: str,
    session_id: str,
) -> bool:
    """Extend an accessible document's inactivity deadline.

    Only a document belonging to an active login session can be
    refreshed. An already expired document cannot be revived.

    Call this from the document-service layer when handling
    a legitimate document interaction.
    """
    validated_document_id = _validate_document_id(document_id)
    owner_id, owner_session_id = _validate_owner(user_id, session_id)

    query = """
        UPDATE public.documents
        SET
            last_activity_at = CURRENT_TIMESTAMP,
            expires_at = CURRENT_TIMESTAMP + INTERVAL '30 minutes'
        WHERE document_id = %s
          AND user_id = %s
          AND session_id = %s
          AND expires_at > CURRENT_TIMESTAMP
          AND EXISTS (
              SELECT 1
              FROM public.user_sessions
              WHERE session_id = %s
                AND user_id = %s
                AND revoked_at IS NULL
                AND expires_at > CURRENT_TIMESTAMP
          )
        RETURNING document_id
    """

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                query,
                (
                    validated_document_id,
                    owner_id,
                    owner_session_id,
                    owner_session_id,
                    owner_id,
                ),
            )
            return cursor.fetchone() is not None


# =============================================================================
# DOCUMENT DELETION
# =============================================================================

def delete_document_record(
    document_id: str,
    user_id: str,
    session_id: str,
) -> bool:
    """Delete metadata only when it belongs to this user and session.

    The document-service layer is responsible for coordinating
    deletion of the corresponding ChromaDB collection.
    """
    validated_document_id = _validate_document_id(document_id)
    owner_id, owner_session_id = _validate_owner(user_id, session_id)

    query = """
        DELETE FROM public.documents
        WHERE document_id = %s
          AND user_id = %s
          AND session_id = %s
        RETURNING document_id
    """

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                query,
                (
                    validated_document_id,
                    owner_id,
                    owner_session_id,
                ),
            )
            return cursor.fetchone() is not None


# =============================================================================
# USER DATABASE OPERATIONS - EXISTING BEHAVIOR PRESERVED
# =============================================================================

def create_user(email: str, password_hash: str) -> dict:
    """Create a user and return safe account details."""
    user_id = uuid4()

    query = """
        INSERT INTO users (user_id, email, password_hash)
        VALUES (%s, %s, %s)
        RETURNING user_id, email, created_at
    """

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                query,
                (user_id, email, password_hash),
            )
            return cursor.fetchone()


def get_user_by_email(email: str) -> dict | None:
    """Retrieve a user by email for registration and login."""
    query = """
        SELECT user_id, email, password_hash, created_at
        FROM users
        WHERE email = %s
    """

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, (email,))
            return cursor.fetchone()
