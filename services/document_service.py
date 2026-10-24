
"""Ingest and retrieve health insurance policy documents."""

import logging
import uuid
from pathlib import Path

from langchain_core.documents import Document

from services.rag_service import (
    CANDIDATE_K,
    TOP_K_RESULTS,
    create_langchain_documents,
    read_pdf,
    rerank_documents,
)
from services.vector_store_service import (
    add_documents,
    get_persistent_client,
    get_persistent_collection,
    search_similar_documents,
)


logger = logging.getLogger(__name__)


def get_collection_name(document_id: str) -> str:
    """Convert a document ID into its ChromaDB collection name."""
    try:
        validated_id = uuid.UUID(hex=document_id)
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("Invalid document ID.") from error

    return f"document_{validated_id.hex}"


def ingest_document(pdf_path: str) -> str:
    """Process a PDF once and store its chunks persistently."""
    chunks = read_pdf(pdf_path)

    documents = create_langchain_documents(
        chunks=chunks,
        source_filename=Path(pdf_path).name,
    )

    document_id = uuid.uuid4().hex
    collection_name = get_collection_name(document_id)
    collection = get_persistent_collection(collection_name)

    try:
        add_documents(
            collection=collection,
            documents=documents,
        )
    except Exception:
        logger.exception(
            "Document ingestion failed: document_id=%s",
            document_id,
        )

        try:
            get_persistent_client().delete_collection(
                name=collection_name
            )
        except Exception:
            logger.exception(
                "Failed to clean up collection: document_id=%s",
                document_id,
            )

        raise

    logger.info(
        "Document indexed: document_id=%s, chunks=%d",
        document_id,
        len(documents),
    )

    return document_id


def retrieve_document_chunks(
    document_id: str,
    question: str,
    top_k: int = TOP_K_RESULTS,
) -> list[Document]:
    """
    Retrieve and rerank chunks from an already indexed PDF.

    Does not extract the PDF or regenerate document embeddings.
    """
    if not isinstance(question, str) or not question.strip():
        raise ValueError("Question cannot be empty.")

    if top_k < 1:
        raise ValueError("top_k must be at least 1.")

    collection_name = get_collection_name(document_id)

    # get_collection raises an error if the document does not exist.
    client = get_persistent_client()
    collection = client.get_collection(name=collection_name)

    # Embed the question and retrieve candidate chunks.
    candidates = search_similar_documents(
        collection=collection,
        question=question,
        top_k=max(CANDIDATE_K, top_k),
    )

    # Rerank candidates using the existing cross-encoder.
    ranked_documents = rerank_documents(
        question=question,
        documents=candidates,
        top_k=top_k,
    )

    logger.info(
        "Document query completed: document_id=%s, candidates=%d, returned=%d",
        document_id,
        len(candidates),
        len(ranked_documents),
    )

    return ranked_documents
