
"""
MODULE NAME
-----------
CHROMADB STORAGE ISOLATION INTEGRATION TEST

PURPOSE
-------
Verify that integration tests use a separate persistent ChromaDB
database without modifying existing application vector storage.

ENVIRONMENT / CONFIGURATION
---------------------------
Uses the safe_test_chroma fixture from tests/conftest.py.

No PostgreSQL database, API server, Gemini key, or embedding
model is required.

DEPENDENCIES
------------
pytest
services.vector_store_service

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Confirm the test directory differs from application storage.
2. Confirm the persistent client uses the test directory.
3. Create a synthetic collection in isolated storage.
4. Insert and retrieve a synthetic document and embedding.
5. Reconnect and verify persistent data is available.
6. Delete only the synthetic test collection.
7. Confirm normal application storage remains unchanged.

SECURITY NOTES
--------------
Never delete, rename, or modify the application's normal
storage/chroma_db directory.

All collection creation and deletion must use the client
verified by safe_test_chroma.
"""

import uuid

from pathlib import Path

from services.vector_store_service import (
    CHROMA_DB_PATH,
    get_chroma_db_path,
    get_persistent_client,
)


# =============================================================================
# READ-ONLY APPLICATION STORAGE INVENTORY
# =============================================================================

def _storage_inventory(directory: Path) -> dict:
    """
    Record file metadata without opening the ChromaDB database.

    This is a lightweight change detector, not a cryptographic
    integrity check. It records relative names, sizes and timestamps.
    """
    if not directory.exists():
        return {}

    inventory = {}

    for path in directory.rglob("*"):
        relative_name = str(path.relative_to(directory))
        metadata = path.stat()

        inventory[relative_name] = (
            path.is_dir(),
            metadata.st_size,
            metadata.st_mtime_ns,
        )

    return inventory


# =============================================================================
# ISOLATION TEST
# =============================================================================

def test_persistent_chroma_storage_is_isolated(safe_test_chroma):
    """
    Verify isolated collection lifecycle and untouched app storage.

    The fixture validates the actual ChromaDB client configuration
    before this test creates any collections.
    """
    application_path = CHROMA_DB_PATH.resolve()
    test_path = safe_test_chroma.resolve()

    assert test_path != application_path
    assert get_chroma_db_path() == test_path

    # Record the existing application directory before test writes.
    application_before = _storage_inventory(application_path)

    client = get_persistent_client()

    actual_client_path = Path(
        client.get_settings().persist_directory
    ).expanduser().resolve()

    assert actual_client_path == test_path

    # Each test uses a unique collection name.
    collection_name = f"document_{uuid.uuid4().hex}"

    existing_names = {
        collection.name
        for collection in client.list_collections()
    }

    assert collection_name not in existing_names

    # Create a collection only in temporary test storage.
    collection = client.create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )

    collection.add(
        ids=["synthetic_chunk_1"],
        embeddings=[[0.1, 0.2, 0.3, 0.4]],
        documents=["Synthetic insurance policy test passage."],
        metadatas=[{"page": 1, "source": "synthetic_test.pdf"}],
    )

    assert collection.count() == 1

    stored = collection.get(
        ids=["synthetic_chunk_1"],
        include=["documents", "metadatas"],
    )

    assert stored["documents"] == [
        "Synthetic insurance policy test passage."
    ]
    assert stored["metadatas"][0]["page"] == 1

    # A second client should access the same persistent test data.
    second_client = get_persistent_client()

    second_client_path = Path(
        second_client.get_settings().persist_directory
    ).expanduser().resolve()

    assert second_client_path == test_path

    reopened_collection = second_client.get_collection(
        name=collection_name
    )

    assert reopened_collection.count() == 1

    # Delete only the synthetic collection from the verified client.
    second_client.delete_collection(
        name=collection_name
    )

    remaining_names = {
        item.name
        for item in second_client.list_collections()
    }

    assert collection_name not in remaining_names

    # The normal application storage must not change.
    application_after = _storage_inventory(application_path)

    assert application_after == application_before, (
        "Application ChromaDB storage changed during isolation test."
    )

    print(
        "\nChromaDB isolation verified:"
        f"\n  Application storage: {application_path}"
        f"\n  Test storage: {test_path}"
        "\n  Synthetic collection created and deleted successfully."
        "\n  Application storage inventory unchanged."
    )
