
"""Tests for persistent document retrieval and grounded answering."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda

from services.document_service import (
    _content_signature,
    _extract_cited_evidence_ids,
    _find_duplicate_document,
    _generate_grounded_response,
    _unique_ready_documents,
    answer_indexed_document_question,
    get_collection_name,
    retrieve_document_chunks,
)

TEST_DOCUMENT_ID = "12aef764515c4cca9d41b24a49b138f2"


def make_document(
    text: str,
    page: int = 1,
    chunk_id: int = 0,
) -> Document:
    """Create a fictional indexed passage for isolated tests."""
    return Document(
        page_content=text,
        metadata={
            "page": page,
            "chunk_id": chunk_id,
            "source": "policy.pdf",
            "document_id": TEST_DOCUMENT_ID,
        },
    )


def test_collection_name_valid():
    """Valid UUIDs produce stable ChromaDB collection names."""
    assert get_collection_name(TEST_DOCUMENT_ID) == (
        f"document_{TEST_DOCUMENT_ID}"
    )


def test_collection_name_invalid():
    """Invalid UUIDs should fail before collection access."""
    with pytest.raises(ValueError, match="Invalid document ID"):
        get_collection_name("not-a-valid-id")


@patch("services.document_service.get_document")
@patch("services.document_service.rerank_documents")
@patch("services.document_service.search_similar_documents")
@patch("services.document_service.get_persistent_client")
def test_retrieve_document_chunks(
    mock_client,
    mock_search,
    mock_rerank,
    mock_get_document,
):
    """Retrieve and rerank chunks from a registered ready collection."""
    mock_collection = MagicMock()
    mock_client.return_value.get_collection.return_value = mock_collection

    mock_get_document.return_value = {
        "document_id": TEST_DOCUMENT_ID,
        "filename": "policy.pdf",
        "collection_name": f"document_{TEST_DOCUMENT_ID}",
        "status": "ready",
    }

    candidate = make_document(
        "Pre-existing conditions have a 24-month waiting period.",
        page=2,
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
    """No evidence should produce a fallback without invoking Gemini."""
    mock_retrieve.return_value = []

    answer = answer_indexed_document_question(
        document_id=TEST_DOCUMENT_ID,
        question="What is covered?",
    )

    assert "no relevant document evidence" in answer.lower()


@patch("services.document_service.get_llm")
@patch("services.document_service.retrieve_document_chunks")
def test_answer_uses_grounded_context(
    mock_retrieve,
    mock_get_llm,
):
    """The LLM should receive the question and numbered PDF evidence."""
    mock_retrieve.return_value = [
        make_document(
            "Waiting period is 24 continuous months.",
            page=2,
        )
    ]

    captured_prompts: list[str] = []

    def fake_llm(prompt):
        captured_prompts.append(prompt.to_string())

        return SimpleNamespace(
            content="The waiting period is 24 months [E1]."
        )

    mock_get_llm.return_value = RunnableLambda(fake_llm)

    answer = answer_indexed_document_question(
        document_id=TEST_DOCUMENT_ID,
        question="What is the waiting period?",
    )

    assert answer == "The waiting period is 24 months [E1]."

    assert "What is the waiting period?" in captured_prompts[0]
    assert "Waiting period is 24 continuous months." in captured_prompts[0]
    assert "PDF page: 2" in captured_prompts[0]
    assert "[E1]" in captured_prompts[0]

    # Confirm the citation-format instruction reaches Gemini.
    assert "comma-separated evidence IDs" in captured_prompts[0]
    assert "NEVER use citation ranges" in captured_prompts[0]

    mock_get_llm.assert_called_once()


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("A waiting period [E1].", {"E1"}),
        ("Two sources [E1, E2].", {"E1", "E2"}),
        ("Two sources [E1][E2].", {"E1", "E2"}),
        (
            "Three sources [E1, E2, E3].",
            {"E1", "E2", "E3"},
        ),
        ("No evidence reference.", set()),
    ],
)
def test_extract_grouped_citations(answer, expected):
    """Grouped citation references must be parsed individually."""
    assert _extract_cited_evidence_ids(answer) == expected


# NEW: Regression tests for malformed evidence citations.
@pytest.mark.parametrize(
    "answer",
    [
        "Waiting periods [E1–E4].",
        "Waiting periods [E1-E4].",
        "Waiting periods [E1—E4].",
        "Waiting periods [E1 to E4].",
        "Waiting periods [E1; E2].",
        "Waiting periods [E1, E2–E4].",
    ],
)
def test_malformed_citation_formats_are_rejected(answer):
    """Unsupported citation formats must not be silently ignored."""
    with pytest.raises(
        ValueError,
        match="invalid citation format",
    ):
        _extract_cited_evidence_ids(answer)


@patch("services.document_service.get_llm")
def test_grouped_citations_are_validated(mock_get_llm):
    """Both IDs in a grouped citation should appear as cited evidence."""
    documents = [
        make_document("Annual deductible is INR 10,000.", page=1),
        make_document(
            "Room rent is limited to INR 5,000.",
            page=2,
            chunk_id=1,
        ),
    ]

    def fake_llm(prompt):
        return SimpleNamespace(
            content="Both conditions apply [E1, E2]."
        )

    mock_get_llm.return_value = RunnableLambda(fake_llm)

    result = _generate_grounded_response(
        "Compare the policy conditions.",
        documents,
    )

    assert result["cited_evidence_ids"] == ["E1", "E2"]
    assert result["citation_warning"] is None


@patch("services.document_service.get_llm")
def test_unknown_grouped_citation_is_rejected(mock_get_llm):
    """An invalid ID must not be hidden inside a citation group."""
    documents = [
        make_document("Annual deductible is INR 10,000.")
    ]

    mock_get_llm.return_value = RunnableLambda(
        lambda prompt: SimpleNamespace(
            content="The deductible is INR 10,000 [E1, E99]."
        )
    )

    with pytest.raises(
        ValueError,
        match="unsupported evidence IDs",
    ):
        _generate_grounded_response(
            "What is the deductible?",
            documents,
        )


# NEW: Verify malformed references are rejected in the full answer flow.
@patch("services.document_service.get_llm")
def test_generated_answer_rejects_citation_range(mock_get_llm):
    """A valid citation elsewhere must not hide a malformed range."""
    documents = [
        make_document("Deductible is INR 10,000.", page=1),
        make_document(
            "Room rent is INR 5,000 per day.",
            page=2,
            chunk_id=1,
        ),
    ]

    mock_get_llm.return_value = RunnableLambda(
        lambda prompt: SimpleNamespace(
            content=(
                "Deductible is INR 10,000 [E1]. "
                "Room rent is INR 5,000 [E1–E2]."
            )
        )
    )

    with pytest.raises(
        ValueError,
        match="invalid citation format",
    ):
        _generate_grounded_response(
            "Compare the deductible and room rent.",
            documents,
        )


def test_identical_content_has_same_signature():
    """Filename and document ID should not affect content equality."""
    first = make_document(
        "Annual deductible is INR 10,000.",
        page=1,
    )

    second = Document(
        page_content="Annual deductible is INR 10,000.",
        metadata={
            "source": "renamed.pdf",
            "document_id": "different-id",
            "page": 1,
            "chunk_id": 0,
        },
    )

    assert _content_signature([first]) == _content_signature([second])


def test_different_content_has_different_signature():
    """Different policy terms must not be treated as duplicates."""
    first = make_document("Deductible is INR 10,000.")
    second = make_document("Deductible is INR 20,000.")

    assert _content_signature([first]) != _content_signature([second])


@patch("services.document_service._stored_document_signature")
@patch("services.document_service.list_documents")
def test_duplicate_document_is_detected(
    mock_list_documents,
    mock_stored_signature,
):
    """An existing content match should prevent another indexing."""
    documents = [
        make_document("Annual deductible is INR 10,000.")
    ]

    existing = {
        "document_id": TEST_DOCUMENT_ID,
        "filename": "original.pdf",
        "collection_name": f"document_{TEST_DOCUMENT_ID}",
        "status": "ready",
    }

    mock_list_documents.return_value = [existing]
    mock_stored_signature.return_value = _content_signature(documents)

    duplicate = _find_duplicate_document(documents)

    assert duplicate == existing


@patch("services.document_service._stored_document_signature")
def test_existing_duplicate_records_are_filtered(mock_signature):
    """Identical indexed PDFs should appear only once in a query."""
    first = {
        "document_id": "first",
        "filename": "policy.pdf",
        "collection_name": "collection_first",
        "status": "ready",
    }

    second = {
        "document_id": "second",
        "filename": "renamed_policy.pdf",
        "collection_name": "collection_second",
        "status": "ready",
    }

    third = {
        "document_id": "third",
        "filename": "different.pdf",
        "collection_name": "collection_third",
        "status": "ready",
    }

    mock_signature.side_effect = [
        "same-content-hash",
        "same-content-hash",
        "different-content-hash",
    ]

    unique = _unique_ready_documents([first, second, third])

    assert unique == [first, third]
