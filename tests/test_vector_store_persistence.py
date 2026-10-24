"""Tests for persistent ChromaDB storage."""

import subprocess
import sys
import uuid
from pathlib import Path

import chromadb


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_persistent_collection_survives_restart(tmp_path):
    """Verify stored data survives across Python processes."""

    # Each test gets a unique collection in a temporary database.
    database_path = tmp_path / "chroma_db"
    collection_name = f"test_{uuid.uuid4().hex}"

    # Step 1: Create a persistent database and collection.
    client = chromadb.PersistentClient(
        path=str(database_path)
    )

    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )

    # Step 2: Store one sample document chunk.
    collection.add(
        ids=["chunk_1"],
        embeddings=[[1.0, 0.0, 0.0]],
        documents=["Hospitalization is covered."],
        metadatas=[{"page": 1}],
    )

    assert collection.count() == 1

    # Step 3: Reopen the database in a separate Python process.
    # This verifies persistence beyond the original process.
    script = """
import chromadb
import sys

client = chromadb.PersistentClient(path=sys.argv[1])
collection = client.get_collection(name=sys.argv[2])
result = collection.get(ids=["chunk_1"])

assert result["documents"] == ["Hospitalization is covered."]
assert result["metadatas"][0]["page"] == 1

print("Persistence verified")
"""

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(database_path),
            collection_name,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )

    assert "Persistence verified" in result.stdout
