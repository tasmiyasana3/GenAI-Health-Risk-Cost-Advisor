
"""Automated tests for PDF chunking and document metadata."""

import pytest

from services.rag_service import (
    split_text_into_chunks,
    create_langchain_documents,
    read_pdf,
)


def test_empty_text_returns_no_chunks():
    assert split_text_into_chunks("   ") == []


def test_chunking_preserves_text():
    text = "First sentence. Second sentence. Third sentence."

    chunks = split_text_into_chunks(
        text,
        chunk_size=35,
        overlap=10,
    )

    assert chunks
    assert all(chunk.strip() for chunk in chunks)
    assert "First sentence." in " ".join(chunks)
    assert "Third sentence." in " ".join(chunks)


def test_invalid_chunk_configuration():
    with pytest.raises(ValueError):
        split_text_into_chunks("Example.", chunk_size=0)

    with pytest.raises(ValueError):
        split_text_into_chunks(
            "Example.",
            chunk_size=100,
            overlap=100,
        )


def test_langchain_document_metadata():
    chunks = [
        {"page": 2, "text": "Waiting period: 24 months."},
        {"page": 3, "text": "Routine dental treatment excluded."},
    ]

    documents = create_langchain_documents(
        chunks,
        "sample_policy.pdf",
    )

    assert len(documents) == 2
    assert documents[0].metadata["page"] == 2
    assert documents[0].metadata["source"] == "sample_policy.pdf"
    assert documents[0].metadata["chunk_id"] == 0
    assert documents[1].metadata["page"] == 3
    assert documents[1].metadata["chunk_id"] == 1


def test_invalid_pdf_extension(tmp_path):
    file_path = tmp_path / "policy.txt"
    file_path.write_text("Not a PDF")

    with pytest.raises(ValueError, match="Only PDF"):
        read_pdf(str(file_path))
