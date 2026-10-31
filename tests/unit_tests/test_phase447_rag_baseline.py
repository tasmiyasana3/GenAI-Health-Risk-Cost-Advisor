
"""Phase 4.4.7 instrumentation contract tests, without Gemini or PostgreSQL."""

from unittest.mock import Mock

from langchain_core.documents import Document

from services import document_service
from services.rag_metrics import record_rag_request


def test_candidate_count_is_measured(monkeypatch):
    monkeypatch.setattr(
        document_service,
        "get_persistent_client",
        lambda: Mock(get_collection=Mock(return_value=Mock())),
    )

    monkeypatch.setattr(
        document_service,
        "search_similar_documents",
        lambda **kwargs: [
            Document(
                page_content="Example",
                metadata={"page": 1},
            )
        ],
    )

    metadata = {
        "collection_name": "document_test",
        "filename": "synthetic.pdf",
        "document_id": "synthetic-id",
    }

    with record_rag_request() as metrics:
        result = document_service._retrieve_candidates(
            metadata,
            "deductible",
            6,
        )

    assert len(result) == 1
    assert result[0].metadata["source"] == "synthetic.pdf"
    assert metrics.candidate_chunks == 1
    assert metrics.summary()["timings_ms"]["vector_search"] >= 0


def test_no_evidence_skips_llm_and_keeps_response_shape(monkeypatch):
    monkeypatch.setattr(
        document_service,
        "get_llm",
        lambda: (_ for _ in ()).throw(
            AssertionError("LLM must not be called")
        ),
    )

    with record_rag_request() as metrics:
        result = document_service._generate_grounded_response(
            "Question?",
            [],
        )

    assert result["citations"] == []
    assert result["cited_evidence_ids"] == []
    assert "answer" in result
    assert metrics.evidence_chunks == 0
