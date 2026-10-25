
"""Automated tests for the FastAPI application endpoints."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)

DOCUMENT_ID = "3feafa1c270f4fa7864412ddbc84c11c"


def test_health_endpoint():
    """The health endpoint should confirm the server is running."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@patch("api.main.predict_insurance_cost")
def test_predict_endpoint(mock_predict):
    """Prediction should pass customer data to the ML service."""
    mock_predict.return_value = 15000.0

    response = client.post(
        "/predict",
        json={"customer_data": {"age": 30}},
    )

    assert response.status_code == 200
    assert response.json()["estimated_insurance_cost"] == 15000.0

    mock_predict.assert_called_once_with({"age": 30})


@patch("api.main.ingest_document")
def test_upload_document_success(mock_ingest):
    """One PDF should be accepted through the batch upload endpoint."""
    mock_ingest.return_value = DOCUMENT_ID

    response = client.post(
        "/documents",
        files=[
            (
                "files",
                (
                    "policy.pdf",
                    b"%PDF-1.4\nfake test content",
                    "application/pdf",
                ),
            )
        ],
    )

    assert response.status_code == 201

    data = response.json()

    assert data["total_files"] == 1
    assert data["successful"] == 1
    assert data["failed"] == 0

    assert data["documents"][0]["document_id"] == DOCUMENT_ID
    assert data["documents"][0]["status"] == "ready"

    mock_ingest.assert_called_once()


@patch("api.main.ingest_document")
def test_upload_two_documents(mock_ingest):
    """Two PDFs should be processed in one request."""
    mock_ingest.side_effect = [
        DOCUMENT_ID,
        "1234567890abcdef1234567890abcdef",
    ]

    response = client.post(
        "/documents",
        files=[
            (
                "files",
                (
                    "first.pdf",
                    b"%PDF-1.4\nfirst test document",
                    "application/pdf",
                ),
            ),
            (
                "files",
                (
                    "second.pdf",
                    b"%PDF-1.4\nsecond test document",
                    "application/pdf",
                ),
            ),
        ],
    )

    assert response.status_code == 201

    data = response.json()

    assert data["total_files"] == 2
    assert data["successful"] == 2
    assert data["failed"] == 0
    assert len(data["documents"]) == 2

    assert mock_ingest.call_count == 2


@patch("api.main.ingest_document")
def test_upload_rejects_non_pdf(mock_ingest):
    """
    Invalid files receive a per-file failure result.

    The existing batch endpoint returns HTTP 201 for a processed
    batch even when an individual file fails validation.
    """
    response = client.post(
        "/documents",
        files=[
            (
                "files",
                (
                    "notes.txt",
                    b"Not a PDF",
                    "text/plain",
                ),
            )
        ],
    )

    assert response.status_code == 201

    data = response.json()

    assert data["successful"] == 0
    assert data["failed"] == 1
    assert data["documents"][0]["status"] == "failed"
    assert "Only PDF files" in data["documents"][0]["error"]

    mock_ingest.assert_not_called()


@patch("api.main.ingest_document")
def test_upload_rejects_duplicate_content(mock_ingest):
    """Duplicate detection should be reported as a file-level failure."""
    mock_ingest.side_effect = ValueError(
        "This PDF content is already indexed."
    )

    response = client.post(
        "/documents",
        files=[
            (
                "files",
                (
                    "duplicate.pdf",
                    b"%PDF-1.4\nfake test content",
                    "application/pdf",
                ),
            )
        ],
    )

    assert response.status_code == 201

    data = response.json()

    assert data["successful"] == 0
    assert data["failed"] == 1
    assert "already indexed" in data["documents"][0]["error"]


@patch("api.main.ingest_document")
def test_upload_rejects_more_than_three_files(mock_ingest):
    """The endpoint must enforce its three-PDF batch limit."""
    files = [
        (
            "files",
            (
                f"policy_{index}.pdf",
                b"%PDF-1.4\nfake test content",
                "application/pdf",
            ),
        )
        for index in range(4)
    ]

    response = client.post("/documents", files=files)

    assert response.status_code == 422
    mock_ingest.assert_not_called()


@patch("api.main.answer_multi_document_question")
def test_ask_multiple_documents(mock_answer):
    """Multi-document answers should preserve citation metadata."""
    mock_answer.return_value = {
        "answer": "The deductible is INR 10,000 [E1].",
        "citations": [
            {
                "citation_id": "E1",
                "document_id": DOCUMENT_ID,
                "filename": "policy.pdf",
                "page": 1,
                "chunk_id": 0,
                "excerpt": "Annual deductible: INR 10,000.",
            }
        ],
        "cited_evidence_ids": ["E1"],
        "citation_warning": None,
        "sources": [
            {
                "document_id": DOCUMENT_ID,
                "filename": "policy.pdf",
            }
        ],
    }

    response = client.post(
        "/documents/ask",
        json={
            "question": "What is the annual deductible?",
            "document_ids": [DOCUMENT_ID],
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert "[E1]" in data["answer"]
    assert data["cited_evidence_ids"] == ["E1"]
    assert data["citations"][0]["page"] == 1

    mock_answer.assert_called_once_with(
        question="What is the annual deductible?",
        document_ids=[DOCUMENT_ID],
    )


@patch("api.main.answer_indexed_document_question")
def test_ask_document_success(mock_answer):
    """The single-document endpoint should return the service answer."""
    mock_answer.return_value = (
        "The waiting period is 24 months [E1]."
    )

    response = client.post(
        f"/documents/{DOCUMENT_ID}/ask",
        json={
            "question": (
                "What is the waiting period for "
                "pre-existing conditions?"
            )
        },
    )

    assert response.status_code == 200
    assert "24 months" in response.json()["answer"]

    mock_answer.assert_called_once()


@patch("api.main.answer_indexed_document_question")
def test_ask_document_invalid_id(mock_answer):
    """Invalid document IDs should return HTTP 422."""
    mock_answer.side_effect = ValueError("Invalid document ID.")

    response = client.post(
        "/documents/invalid-id/ask",
        json={"question": "What is covered?"},
    )

    assert response.status_code == 422


@patch("api.main.answer_indexed_document_question")
def test_ask_document_service_failure(mock_answer):
    """Unexpected internal errors should not expose implementation details."""
    mock_answer.side_effect = RuntimeError(
        "Internal service failure"
    )

    response = client.post(
        f"/documents/{DOCUMENT_ID}/ask",
        json={"question": "What is covered?"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "Unable to answer the document question."
    )
