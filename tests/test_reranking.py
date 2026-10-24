
"""Automated tests for RAG reranking."""

from unittest.mock import patch

import numpy as np
from langchain_core.documents import Document

from services.rag_service import rerank_documents


def test_reranker_orders_documents_by_relevance():
    """The highest-scoring document should rank first."""

    documents = [
        Document(
            page_content="An unrelated claims example.",
            metadata={"page": 4},
        ),
        Document(
            page_content="Pre-existing conditions require 24 months.",
            metadata={"page": 2},
        ),
        Document(
            page_content="General policy information.",
            metadata={"page": 1},
        ),
    ]

    # Fake model scores let us test ordering without loading a model.
    with patch("services.rag_service.get_reranker") as mock_loader:
        mock_loader.return_value.predict.return_value = np.array(
            [0.2, 0.95, 0.1]
        )

        results = rerank_documents(
            question="What is the waiting period?",
            documents=documents,
            top_k=2,
        )

    assert len(results) == 2
    assert results[0].metadata["page"] == 2
    assert results[1].metadata["page"] == 4


def test_reranker_returns_empty_for_no_documents():
    """No candidates should produce an empty result."""

    assert rerank_documents("Any question", []) == []
