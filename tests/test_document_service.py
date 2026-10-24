
"""Tests for persistent document retrieval and Gemini answering."""

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.runnables import RunnableLambda
from langchain_core.documents import Document

from services.document_service import (
    answer_indexed_document_question,
    get_collection_name,
    retrieve_document_chunks,
)


TEST_DOCUMENT_ID = "12aef764515c4cca9d41b24a49b138f2"


def test_collection_name_valid():
    """A valid document ID produces the expected collection name."""
    assert get_collection_name(TEST_DOCUMENT_ID) == (
        f"document_{TEST_DOCUMENT_ID}"
    )


def test_collection_name_invalid():
    """Invalid IDs are rejected before accessing ChromaDB."""
    with pytest.raises(ValueError, match="Invalid document ID"):
        get_collection_name("not-a-valid-id")


@patch("services.document_service.rerank_documents")
@patch("services.document_service.search_similar_documents")
@patch("services.document_service.get_persistent_client")
def test_retrieve_document_chunks(
    mock_client,
    mock_search,
    mock_rerank,
):
    """Retrieve and rerank chunks from the selected collection."""
    mock_collection = MagicMock()
    mock_client.return_value.get_collection.return_value = mock_collection

    candidate = Document(
        page_content="Pre-existing conditions have a 24-month waiting period.",
        metadata={"page": 2},
    )

    mock_search.return_value = [candidate]
    mock_rerank.return_value = [candidate]

    results = retrieve_document_chunks(
        document_id=TEST_DOCUMENT_ID,
        question="What is the waiting period?",
    )

    assert results == [candidate]

    mock_client.return_value.get_collection.assert_called_once_with(
        name=f"document_{TEST_DOCUMENT_ID}"
    )

    mock_search.assert_called_once_with(
        collection=mock_collection,
        question="What is the waiting period?",
        top_k=6,
    )

    mock_rerank.assert_called_once_with(
        question="What is the waiting period?",
        documents=[candidate],
        top_k=3,
    )


@patch("services.document_service.retrieve_document_chunks")
def test_answer_without_relevant_chunks(mock_retrieve):
    """Return a fallback response when no chunks are retrieved."""
    mock_retrieve.return_value = []

    answer = answer_indexed_document_question(
        document_id=TEST_DOCUMENT_ID,
        question="What is covered?",
    )

    assert "could not find relevant text" in answer.lower()


@patch("config.get_llm")
@patch("services.document_service.retrieve_document_chunks")
def test_answer_uses_grounded_context(
    mock_retrieve,
    mock_get_llm,
):
    """Verify that retrieved evidence reaches the LLM with page citations."""

    mock_retrieve.return_value = [
        Document(
            page_content="Waiting period is 24 continuous months.",
            metadata={"page": 2},
        )
    ]

    captured_prompts = []

    def fake_llm(prompt):
        """Capture the formatted prompt without calling Gemini."""
        captured_prompts.append(prompt.to_string())

        return MagicMock(
            content="The waiting period is 24 months [Page 2]."
        )

    mock_get_llm.return_value = RunnableLambda(fake_llm)

    answer = answer_indexed_document_question(
        document_id=TEST_DOCUMENT_ID,
        question="What is the waiting period?",
    )

    assert answer == "The waiting period is 24 months [Page 2]."

    # Confirm the model received the actual question.
    assert "What is the waiting period?" in captured_prompts[0]

    # Confirm the retrieved policy evidence was included.
    assert "Waiting period is 24 continuous months." in captured_prompts[0]

    # Confirm page metadata was preserved in the context.
    assert "[Page 2]" in captured_prompts[0]

    mock_get_llm.assert_called_once()
