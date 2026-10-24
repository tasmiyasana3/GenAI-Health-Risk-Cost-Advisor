
"""Manage temporary and persistent ChromaDB vector collections."""

import logging
import uuid
from pathlib import Path

import chromadb
from chromadb.api.models.Collection import Collection
from langchain_core.documents import Document

from services.embedding_service import generate_embeddings


logger = logging.getLogger(__name__)

# Local directory for persistent vector storage.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHROMA_DB_PATH = PROJECT_ROOT / "storage" / "chroma_db"


def get_persistent_client() -> chromadb.ClientAPI:
    """Connect to the local persistent ChromaDB database."""
    return chromadb.PersistentClient(
        path=str(CHROMA_DB_PATH)
    )


def get_persistent_collection(
    collection_name: str,
) -> Collection:
    """Get an existing persistent collection or create a new one."""
    if not collection_name.strip():
        raise ValueError("Collection name cannot be empty.")

    client = get_persistent_client()

    return client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )


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


def add_documents(
    collection: Collection,
    documents: list[Document],
) -> None:
    """Generate embeddings and store document chunks."""
    if not documents:
        raise ValueError("No documents were provided.")

    texts = [document.page_content for document in documents]

    embeddings = generate_embeddings(texts)

    # These IDs identify individual chunks, not uploaded PDFs.
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
