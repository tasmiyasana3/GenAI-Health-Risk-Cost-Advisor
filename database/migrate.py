
"""
PostgreSQL migration runner for the Health RAG application.

Usage:
    python -m database.migrate --database health_rag_migration_test

Features:
    - Explicit database selection
    - Versioned SQL migrations
    - SHA-256 checksum verification
    - Transactional migration execution
    - Controlled legacy checksum initialization
    - Advisory lock to prevent concurrent migration runners
"""

import argparse
import hashlib
import os
from pathlib import Path

import psycopg


MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

HISTORY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS public.schema_migrations (
    version VARCHAR(20) PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

# PostgreSQL advisory lock identifier for this application's migrations.
MIGRATION_LOCK_ID = 72841021


def get_migration_files() -> list[Path]:
    """Return migration files in version order."""
    files = sorted(MIGRATIONS_DIR.glob("[0-9]*_*.sql"))

    if not files:
        raise RuntimeError("No migration files found.")

    versions = [path.name.split("_", 1)[0] for path in files]

    if len(versions) != len(set(versions)):
        raise RuntimeError("Duplicate migration versions found.")

    return files


def calculate_checksum(path: Path) -> str:
    """Calculate the SHA-256 checksum of a SQL migration."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checksum_column_exists(connection: psycopg.Connection) -> bool:
    """Check whether migration history has a checksum column."""
    row = connection.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'schema_migrations'
              AND column_name = 'checksum'
        )
        """
    ).fetchone()

    return bool(row[0])


def get_connection_kwargs(database_name: str) -> dict:
    """Build PostgreSQL connection settings."""
    kwargs = {
        "dbname": database_name,
        "connect_timeout": 5,
        "autocommit": True,
    }

    for env_name, argument in (
        ("PGHOST", "host"),
        ("PGPORT", "port"),
        ("PGUSER", "user"),
        ("PGPASSWORD", "password"),
    ):
        value = os.getenv(env_name)
        if value:
            kwargs[argument] = value

    return kwargs


def run_migrations(database_name: str) -> None:
    """Verify applied migrations and apply pending migrations."""
    migration_files = get_migration_files()

    migration_info = {
        path.stem.split("_", 1)[0]: {
            "path": path,
            "checksum": calculate_checksum(path),
        }
        for path in migration_files
    }

    with psycopg.connect(
        **get_connection_kwargs(database_name)
    ) as connection:

        actual_database = connection.execute(
            "SELECT current_database()"
        ).fetchone()[0]

        print(f"Connected to database: {actual_database}")

        baseline_exists = connection.execute(
            "SELECT to_regclass('public.documents')"
        ).fetchone()[0]

        if baseline_exists is None:
            raise RuntimeError(
                "Missing baseline documents table. "
                "Initialize database/schema.sql first."
            )

        # Prevent two migration runners from executing concurrently.
        acquired = connection.execute(
            "SELECT pg_try_advisory_lock(%s)",
            (MIGRATION_LOCK_ID,),
        ).fetchone()[0]

        if not acquired:
            raise RuntimeError(
                "Another migration runner is already active."
            )

        try:
            connection.execute(HISTORY_TABLE_SQL)

            has_checksums = checksum_column_exists(connection)

            if has_checksums:
                rows = connection.execute(
                    """
                    SELECT version, checksum
                    FROM public.schema_migrations
                    """
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT version, NULL
                    FROM public.schema_migrations
                    """
                ).fetchall()

            history = dict(rows)

            # Verify every recorded migration has a matching file.
            for version in history:
                if version not in migration_info:
                    raise RuntimeError(
                        f"Unknown applied migration: {version}"
                    )

            if has_checksums:
                # Once checksum support exists, NULL is not acceptable.
                for version, stored_checksum in history.items():
                    if stored_checksum is None:
                        raise RuntimeError(
                            f"MISSING CHECKSUM for migration {version}."
                        )

                    expected = migration_info[version]["checksum"]

                    if stored_checksum != expected:
                        raise RuntimeError(
                            f"CHECKSUM MISMATCH for migration {version}. "
                            "Restore the original migration file."
                        )
            else:
                # Legacy database upgrade is permitted only when
                # migrations 001-003 have already been recorded
                # and migration 004 is still pending.
                expected_legacy_versions = {"001", "002", "003"}

                if set(history) != expected_legacy_versions:
                    raise RuntimeError(
                        "Unexpected legacy migration history. "
                        "Manual verification is required."
                    )

                if "004" not in migration_info:
                    raise RuntimeError(
                        "Missing checksum upgrade migration 004."
                    )

            for migration_file in migration_files:
                version, description = migration_file.stem.split(
                    "_", 1
                )

                if version in history:
                    print(f"SKIP  {migration_file.name}")
                    continue

                migration_sql = migration_file.read_text(
                    encoding="utf-8"
                )

                print(f"APPLY {migration_file.name}")

                with connection.transaction():
                    connection.execute(migration_sql)

                    if version == "004":
                        has_checksums = True

                    if has_checksums:
                        connection.execute(
                            """
                            INSERT INTO public.schema_migrations
                                (version, description, checksum)
                            VALUES (%s, %s, %s)
                            """,
                            (
                                version,
                                description.replace("_", " "),
                                migration_info[version]["checksum"],
                            ),
                        )
                    else:
                        connection.execute(
                            """
                            INSERT INTO public.schema_migrations
                                (version, description)
                            VALUES (%s, %s)
                            """,
                            (
                                version,
                                description.replace("_", " "),
                            ),
                        )

                    # Backfill only during the controlled legacy
                    # upgrade from migration 003 to 004.
                    if version == "004" and history == {
                        "001": None,
                        "002": None,
                        "003": None,
                    }:
                        for legacy_version in ("001", "002", "003"):
                            connection.execute(
                                """
                                UPDATE public.schema_migrations
                                SET checksum = %s
                                WHERE version = %s
                                  AND checksum IS NULL
                                """,
                                (
                                    migration_info[
                                        legacy_version
                                    ]["checksum"],
                                    legacy_version,
                                ),
                            )

                history[version] = migration_info[version]["checksum"]

                print(f"DONE  {migration_file.name}")

            if has_checksums:
                missing_count = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM public.schema_migrations
                    WHERE checksum IS NULL
                    """
                ).fetchone()[0]

                if missing_count:
                    raise RuntimeError(
                        "Migration history contains missing checksums."
                    )

        finally:
            connection.execute(
                "SELECT pg_advisory_unlock(%s)",
                (MIGRATION_LOCK_ID,),
            )

    print("Migration check complete.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply PostgreSQL schema migrations."
    )
    parser.add_argument(
        "--database",
        required=True,
        help="Existing PostgreSQL database name",
    )

    args = parser.parse_args()
    run_migrations(args.database)


if __name__ == "__main__":
    main()
