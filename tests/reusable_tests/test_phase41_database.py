
"""
Phase 4.1 — PostgreSQL database structure verification.

These tests confirm that the schema created during Phase 4.1
still matches the application's requirements.

The tests are read-only:
    - No migrations are executed.
    - No tables are created or dropped.
    - No application records are modified.

All tests use the shared safe_test_database fixture.
"""

import psycopg
import pytest

from psycopg.rows import dict_row


TEST_DATABASE_NAME = "health_rag_migration_test"
TEST_DATABASE_OWNER = "tasmiyasana"


# Run the database safety checks before every test in this module.
#
# pytest automatically finds the fixture in conftest.py.
pytestmark = pytest.mark.usefixtures("safe_test_database")


@pytest.fixture
def database_connection():
    """
    Provide a PostgreSQL connection for schema inspection.

    The database-owner role is used because the tests inspect
    PostgreSQL metadata and migration history.

    The connection is automatically closed after each test.
    """

    with psycopg.connect(
        dbname=TEST_DATABASE_NAME,
        user=TEST_DATABASE_OWNER,
        row_factory=dict_row,
    ) as connection:

        # Confirm the connection is using the intended database.
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_database() AS database_name"
            )

            result = cursor.fetchone()

            assert result["database_name"] == TEST_DATABASE_NAME

        yield connection


def get_table_columns(connection, table_name: str) -> set[str]:
    """
    Retrieve the column names belonging to a PostgreSQL table.

    Parameters
    ----------
    connection:
        An active PostgreSQL connection.

    table_name:
        Name of the table whose columns should be inspected.

    Returns
    -------
    set[str]
        A set containing the table's column names.

    Why use information_schema?
    ---------------------------
    PostgreSQL exposes table metadata through information_schema.
    This lets us inspect the schema without reading user records.
    """

    query = """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = %s
    """

    with connection.cursor() as cursor:

        # The table name is passed as a query parameter.
        # This avoids building SQL by concatenating user input.
        cursor.execute(query, (table_name,))

        rows = cursor.fetchall()

    # Convert database rows into a set for simple membership checks.
    return {row["column_name"] for row in rows}


def test_required_tables_exist(database_connection):
    """
    Verify the three tables required by Phase 4.1.

    users:
        Stores user account information.

    documents:
        Stores insurance document metadata.

    schema_migrations:
        Records which database migrations were applied.
    """

    query = """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name IN (
              'users',
              'documents',
              'schema_migrations'
          )
    """

    with database_connection.cursor() as cursor:
        cursor.execute(query)

        rows = cursor.fetchall()

    actual_tables = {row["table_name"] for row in rows}

    expected_tables = {
        "users",
        "documents",
        "schema_migrations",
    }

    assert actual_tables == expected_tables


def test_users_table_columns(database_connection):
    """
    Verify the fields needed for user registration and login.
    """

    actual_columns = get_table_columns(
        database_connection,
        "users",
    )

    required_columns = {
        "user_id",       # Unique account identifier (UUID).
        "email",         # Email used for account lookup.
        "password_hash", # Argon2id password hash, not plaintext.
        "created_at",    # Account creation timestamp.
    }

    # Other columns may be added in future migrations.
    # Therefore, require these columns without forbidding extras.
    assert required_columns.issubset(actual_columns)


def test_documents_table_columns(database_connection):
    """
    Verify document metadata and ownership-related fields.
    """

    actual_columns = get_table_columns(
        database_connection,
        "documents",
    )

    required_columns = {
        "document_id",     # Unique identifier for a document.
        "filename",        # Original uploaded PDF filename.
        "collection_name", # Associated ChromaDB collection.
        "status",          # Processing state of the document.
        "uploaded_at",     # Timestamp when the PDF was uploaded.
        "user_id",         # Nullable owner identifier.
    }

    assert required_columns.issubset(actual_columns)


def test_migration_history_has_checksums(database_connection):
    """
    Verify that migrations are recorded with SHA-256 checksums.

    A checksum is a fingerprint of a migration file.

    The migration runner uses these fingerprints to detect
    unexpected changes to previously applied migrations.
    """

    actual_columns = get_table_columns(
        database_connection,
        "schema_migrations",
    )

    required_columns = {
        "version",
        "description",
        "applied_at",
        "checksum",
    }

    assert required_columns.issubset(actual_columns)

    query = """
        SELECT version, checksum
        FROM public.schema_migrations
        ORDER BY version
    """

    with database_connection.cursor() as cursor:
        cursor.execute(query)

        migrations = cursor.fetchall()

    # At least one migration must have been recorded.
    assert migrations, "Migration history is unexpectedly empty."

    for migration in migrations:

        checksum = migration["checksum"]

        # SHA-256 produces 64 hexadecimal characters.
        assert checksum is not None
        assert len(checksum) == 64

        # Verify that every character is valid hexadecimal.
        assert all(
            character in "0123456789abcdef"
            for character in checksum
        )


def test_application_role_has_limited_user_permissions(
    database_connection,
):
    """
    Verify least-privilege access for the application role.

    The application may:
        - SELECT users to retrieve account information.
        - INSERT users to register new accounts.

    It must not:
        - DELETE user records through its normal database role.

    The application role is health_rag_app.
    """

    query = """
        SELECT
            has_table_privilege(
                'health_rag_app',
                'public.users',
                'SELECT'
            ) AS can_select,

            has_table_privilege(
                'health_rag_app',
                'public.users',
                'INSERT'
            ) AS can_insert,

            has_table_privilege(
                'health_rag_app',
                'public.users',
                'DELETE'
            ) AS can_delete
    """

    with database_connection.cursor() as cursor:
        cursor.execute(query)

        permissions = cursor.fetchone()

    assert permissions["can_select"] is True
    assert permissions["can_insert"] is True
    assert permissions["can_delete"] is False
