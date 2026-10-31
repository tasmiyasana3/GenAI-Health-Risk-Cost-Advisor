
"""
MODULE NAME
-----------
VECTOR STORE SERVICE

PURPOSE
-------
Manage persistent and temporary ChromaDB collections used by
the insurance policy document RAG application.

ENVIRONMENT / CONFIGURATION
---------------------------
CHROMA_DB_PATH:
    Optional directory for persistent vector storage.

    When unset, the application uses:
        storage/chroma_db/

    Integration tests can override this path with a separate
    temporary directory.

DEPENDENCIES
------------
chromadb
langchain_core
services.embedding_service

RESPONSIBILITIES
----------------
1. Resolve the persistent ChromaDB storage directory.
2. Create persistent or temporary ChromaDB clients.
3. Create and retrieve document collections.
4. Store embedded document chunks.
5. Retrieve semantically similar passages.

SECURITY NOTES
--------------
The normal application's ChromaDB directory must never be used
for destructive integration tests.

The storage path is resolved when the client is created so that
pytest environment overrides take effect.

Collection ownership and session authorization are enforced by
the document and database services, not by ChromaDB itself.
"""

import logging
import os
import uuid

from pathlib import Path

import chromadb

from chromadb.api.models.Collection import Collection
from langchain_core.documents import Document

from services.embedding_service import generate_embeddings


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Preserve the existing application storage location.
CHROMA_DB_PATH = PROJECT_ROOT / "storage" / "chroma_db"

CHROMA_DB_ENV_VAR = "CHROMA_DB_PATH"


# =============================================================================
# PERSISTENT STORAGE CONFIGURATION
# =============================================================================

def get_chroma_db_path() -> Path:
    """
    Return the effective persistent ChromaDB directory.

    The environment override is evaluated on each call rather than
    at module import time. This allows pytest to configure a separate
    directory without modifying normal application settings.
    """
    configured_path = os.getenv(CHROMA_DB_ENV_VAR)

    if configured_path is None:
        return CHROMA_DB_PATH.resolve()

    if not configured_path.strip():
        raise ValueError(
            "CHROMA_DB_PATH cannot be empty when configured."
        )

    return Path(configured_path).expanduser().resolve()


def get_persistent_client() -> chromadb.ClientAPI:
    """
    Create a ChromaDB client using the effective storage directory.

    ChromaDB manages the persistent files in this directory.
    """
    storage_path = get_chroma_db_path()

    logger.debug(
        "Connecting to persistent ChromaDB: %s",
        storage_path,
    )

    return chromadb.PersistentClient(
        path=str(storage_path)
    )


def get_persistent_collection(
    collection_name: str,
) -> Collection:
    """Get an existing persistent collection or create a new one."""
    if not isinstance(collection_name, str) or not collection_name.strip():
        raise ValueError("Collection name cannot be empty.")

    client = get_persistent_client()

    return client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )


# =============================================================================
# LEGACY TEMPORARY COLLECTIONS
# =============================================================================

def create_vector_collection() -> Collection:
    """
    Create a temporary vector collection.

    Retained for compatibility with the existing Gradio RAG
    workflow. This will be removed after migration.
    """
    client = chromadb.EphemeralClient()
    collection_name = f"document_{uuid.uuid4().hex}"

    return client.create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )


# =============================================================================
# DOCUMENT INDEXING
# =============================================================================

def add_documents(
    collection: Collection,
    documents: list[Document],
) -> None:
    """Generate embeddings and store document chunks."""
    if not documents:
        raise ValueError("No documents were provided.")

    texts = [document.page_content for document in documents]

    embeddings = generate_embeddings(texts)

    # Chunk IDs identify individual passages, not uploaded PDFs.
    chunk_ids = [
        str(uuid.uuid4())
        for _ in documents
    ]

    metadata = [
        document.metadata
        for document in documents
    ]

    collection.add(
        ids=chunk_ids,
        embeddings=embeddings.tolist(),
        documents=texts,
        metadatas=metadata,
    )

    logger.info(
        "Stored %d document chunks",
        len(documents),
    )


# =============================================================================
# SEMANTIC RETRIEVAL
# =============================================================================

def search_similar_documents(
    collection: Collection,
    question: str,
    top_k: int = 4,
) -> list[Document]:
    """Retrieve document chunks relevant to a question."""
    if not isinstance(question, str) or not question.strip():
        raise ValueError("Question cannot be empty.")

    if top_k < 1:
        raise ValueError("top_k must be at least 1.")

    # An empty collection has no passages to retrieve.
    chunk_count = collection.count()

    if chunk_count == 0:
        return []

    question_embedding = generate_embeddings([question])

    results = collection.query(
        query_embeddings=question_embedding.tolist(),
        n_results=min(top_k, chunk_count),
        include=["documents", "metadatas", "distances"],
    )

    relevant_documents = []

    for text, metadata in zip(
        results["documents"][0],
        results["metadatas"][0],
    ):
        document = Document(
            page_content=text,
            metadata=metadata or {},
        )

        relevant_documents.append(document)

    return relevant_documents