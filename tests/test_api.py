
"""Automated tests for FastAPI endpoints."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app


client = TestClient(app)

DOCUMENT_ID = "3feafa1c270f4fa7864412ddbc84c11c"


def test_health_endpoint():
    """Verify the API health endpoint."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@patch("api.main.predict_insurance_cost")
def test_predict_endpoint(mock_predict):
    """Verify the ML endpoint using a mocked prediction."""
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
    """Verify PDF upload and document indexing."""
    mock_ingest.return_value = DOCUMENT_ID

    response = client.post(
        "/documents",
        files={
            "file": (
                "policy.pdf",
                b"%PDF-1.4\nfake test content",
                "application/pdf",
            )
        },
    )

    assert response.status_code == 201
    assert response.json()["document_id"] == DOCUMENT_ID
    assert response.json()["status"] == "indexed"
    mock_ingest.assert_called_once()


def test_upload_rejects_non_pdf():
    """Verify that unsupported file extensions are rejected."""
    response = client.post(
        "/documents",
        files={
            "file": (
                "notes.txt",
                b"Not a PDF",
                "text/plain",
            )
        },
    )

    assert response.status_code == 415


@patch("api.main.answer_indexed_document_question")
def test_ask_document_success(mock_answer):
    """Verify the document question-answering endpoint."""
    mock_answer.return_value = (
        "The waiting period is 24 months [Page 2]."
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
    """Verify handling of an invalid document ID."""
    mock_answer.side_effect = ValueError(
        "Invalid document ID."
    )

    response = client.post(
        "/documents/invalid-id/ask",
        json={"question": "What is covered?"},
    )

    assert response.status_code == 422


@patch("api.main.answer_indexed_document_question")
def test_ask_document_service_failure(mock_answer):
    """Verify that unexpected internal errors are not exposed."""
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
