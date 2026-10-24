
"""Store and retrieve PDF chunks using ChromaDB."""

import logging
import uuid

import chromadb
from chromadb.api.models.Collection import Collection
from langchain_core.documents import Document

from services.embedding_service import generate_embeddings


logger = logging.getLogger(__name__)


def create_vector_collection() -> Collection:
    """
    Create an isolated, in-memory ChromaDB collection.

    Returns:
        A new ChromaDB collection for one document-processing session.
    """

    # Each call creates a separate in-memory database client.
    client = chromadb.EphemeralClient()

    # A unique collection name avoids naming conflicts.
    collection_name = f"document_{uuid.uuid4().hex}"

    collection = client.create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )

    return collection


def add_documents(
    collection: Collection,
    documents: list[Document],
) -> None:
    """
    Convert document text into embeddings and store it in ChromaDB.
    """

    if not documents:
        raise ValueError("No documents were provided.")

    # Extract the text from each LangChain Document.
    texts = [document.page_content for document in documents]

    # Convert all passages into numerical vectors.
    embeddings = generate_embeddings(texts)

    # Give every stored passage a unique identifier.
    document_ids = [
        str(uuid.uuid4())
        for _ in documents
    ]

    # Keep source filename, page number and chunk ID.
    metadata = [
        document.metadata
        for document in documents
    ]

    # Store the vectors, original text and metadata together.
    collection.add(
        ids=document_ids,
        embeddings=embeddings.tolist(),
        documents=texts,
        metadatas=metadata,
    )

    logger.info("Stored %d document chunks", len(documents))


def search_similar_documents(
    collection: Collection,
    question: str,
    top_k: int = 4,
) -> list[Document]:
    """
    Find document passages semantically related to a question.
    """

    if not question.strip():
        raise ValueError("Question cannot be empty.")

    if top_k < 1:
        raise ValueError("top_k must be at least 1.")

    # Convert the question into a vector using the same model.
    question_embedding = generate_embeddings([question])

    # Search only the requested collection.
    results = collection.query(
        query_embeddings=question_embedding.tolist(),
        n_results=min(top_k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    relevant_documents = []

    # ChromaDB returns results grouped by query.
    for text, metadata in zip(
        results["documents"][0],
        results["metadatas"][0],
    ):
        document = Document(
            page_content=text,
            metadata=metadata,
        )

        relevant_documents.append(document)

    return relevant_documents
