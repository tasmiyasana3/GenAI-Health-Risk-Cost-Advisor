
import os

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv


# Load database credentials from .env
load_dotenv()


def get_db_connection():
    """Create a PostgreSQL connection."""
    return psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        connect_timeout=5,
        row_factory=dict_row,
    )


def register_document(document_id: str, filename: str, collection_name: str):
    """Register a document with initial status 'processing'."""

    query = """
        INSERT INTO documents (document_id, filename, collection_name)
        VALUES (%s, %s, %s)
    """

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                query,
                (document_id, filename, collection_name)
            )


def get_document(document_id: str):
    """Retrieve document metadata by ID."""

    query = """
        SELECT document_id, filename, collection_name,
               status, uploaded_at
        FROM documents
        WHERE document_id = %s
    """

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, (document_id,))
            return cursor.fetchone()


def list_documents():
    """Retrieve all registered documents, newest first."""

    query = """
        SELECT document_id, filename, collection_name,
               status, uploaded_at
        FROM documents
        ORDER BY uploaded_at DESC
    """

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query)
            return cursor.fetchall()


def update_document_status(document_id: str, status: str):
    """Update a document's processing status."""

    allowed_statuses = {"processing", "ready", "failed"}

    if status not in allowed_statuses:
        raise ValueError(f"Invalid document status: {status}")

    query = """
        UPDATE documents
        SET status = %s
        WHERE document_id = %s
        RETURNING document_id
    """

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, (status, document_id))
            if cursor.fetchone() is None:
                raise ValueError(f"Document not found: {document_id}")


def delete_document_record(document_id: str):
    """Delete document metadata from PostgreSQL."""

    query = """
        DELETE FROM documents
        WHERE document_id = %s
        RETURNING document_id
    """

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, (document_id,))
            return cursor.fetchone() is not None
