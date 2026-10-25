
"""Unit tests for Phase 3 PDF evidence and citation handling."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document
from pypdf import PdfWriter

from services.document_service import (
    _build_citations,
    _format_evidence,
    _generate_grounded_response,
)
from services.rag_service import (
    create_langchain_documents,
    read_pdf,
)


@pytest.fixture
def sample_documents() -> list[Document]:
    """Create fictional passages without requiring vector indexing."""
    return [
        Document(
            page_content="Cataract waiting period is twelve months.",
            metadata={
                "document_id": "doc-a",
                "source": "policy-a.pdf",
                "page": 2,
                "chunk_id": 3,
            },
        ),
        Document(
            page_content="Room rent is limited to INR 5,000 per day.",
            metadata={
                "document_id": "doc-b",
                "source": "policy-b.pdf",
                "page": 1,
                "chunk_id": 0,
            },
        ),
    ]


def mock_gemini_response(answer: str):
    """Replace the LLM call while keeping citation processing real."""
    fake_chain = MagicMock()
    fake_chain.invoke.return_value = SimpleNamespace(content=answer)

    return fake_chain


def test_evidence_ids_are_sequential(sample_documents):
    citations = _build_citations(sample_documents)

    assert [item["citation_id"] for item in citations] == [
        "E1",
        "E2",
    ]


def test_citations_preserve_source_metadata(sample_documents):
    citations = _build_citations(sample_documents)

    assert citations[0]["filename"] == "policy-a.pdf"
    assert citations[0]["document_id"] == "doc-a"
    assert citations[0]["page"] == 2
    assert citations[0]["chunk_id"] == 3

    assert citations[1]["filename"] == "policy-b.pdf"
    assert citations[1]["page"] == 1


def test_evidence_context_contains_original_excerpts(sample_documents):
    citations = _build_citations(sample_documents)
    context = _format_evidence(citations)

    assert "[E1]" in context
    assert "[E2]" in context
    assert "Cataract waiting period is twelve months." in context
    assert "Room rent is limited to INR 5,000 per day." in context


def test_invalid_page_number_is_rejected():
    document = Document(
        page_content="Example policy text.",
        metadata={
            "source": "example.pdf",
            "page": 0,
        },
    )

    with pytest.raises(ValueError, match="invalid PDF page number"):
        _build_citations([document])


def test_valid_answer_references_existing_evidence(sample_documents):
    fake_chain = mock_gemini_response(
        "The waiting period is twelve months [E1]."
    )

    with patch("services.document_service.DOCUMENT_PROMPT") as prompt:
        prompt.__or__.return_value = fake_chain

        with patch("services.document_service.get_llm"):
            result = _generate_grounded_response(
                "What is the waiting period?",
                sample_documents,
            )

    assert result["cited_evidence_ids"] == ["E1"]
    assert result["citation_warning"] is None
    assert len(result["citations"]) == 2


def test_unknown_evidence_id_is_rejected(sample_documents):
    fake_chain = mock_gemini_response(
        "The waiting period is twelve months [E99]."
    )

    with patch("services.document_service.DOCUMENT_PROMPT") as prompt:
        prompt.__or__.return_value = fake_chain

        with patch("services.document_service.get_llm"):
            with pytest.raises(
                ValueError,
                match="unsupported evidence IDs",
            ):
                _generate_grounded_response(
                    "What is the waiting period?",
                    sample_documents,
                )


def test_answer_without_citations_returns_warning(sample_documents):
    fake_chain = mock_gemini_response(
        "The waiting period is twelve months."
    )

    with patch("services.document_service.DOCUMENT_PROMPT") as prompt:
        prompt.__or__.return_value = fake_chain

        with patch("services.document_service.get_llm"):
            result = _generate_grounded_response(
                "What is the waiting period?",
                sample_documents,
            )

    assert result["cited_evidence_ids"] == []
    assert result["citation_warning"] is not None


def test_no_evidence_does_not_call_gemini():
    with patch("services.document_service.get_llm") as mock_llm:
        result = _generate_grounded_response(
            "What is the waiting period?",
            [],
        )

    mock_llm.assert_not_called()
    assert result["citations"] == []
    assert "No relevant document evidence" in result["answer"]


def test_chunk_metadata_preserves_one_based_page_number():
    chunks = [
        {"page": 1, "text": "First PDF page."},
        {"page": 2, "text": "Second PDF page."},
    ]

    documents = create_langchain_documents(
        chunks=chunks,
        source_filename="test.pdf",
    )

    assert documents[0].metadata["page"] == 1
    assert documents[1].metadata["page"] == 2
    assert documents[0].metadata["chunk_id"] == 0
    assert documents[1].metadata["chunk_id"] == 1


def test_blank_pdf_does_not_create_false_evidence(tmp_path):
    """Blank pages must not produce fabricated extracted text."""
    pdf_path = tmp_path / "blank_pages.pdf"

    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.add_blank_page(width=300, height=300)

    with pdf_path.open("wb") as pdf_file:
        writer.write(pdf_file)

    with pytest.raises(ValueError, match="No readable text"):
        read_pdf(str(pdf_path))
