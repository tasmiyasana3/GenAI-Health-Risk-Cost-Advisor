
"""
MODULE NAME
-----------
FASTAPI ENDPOINT REGRESSION TESTS

PURPOSE
-------
Verify insurance prediction and document API behavior after
authenticated document ownership was introduced.

ENVIRONMENT / CONFIGURATION
---------------------------
Runs locally with pytest and FastAPI TestClient.

No live PostgreSQL, ChromaDB, or Gemini calls are required.

DEPENDENCIES
------------
pytest
fastapi.testclient
unittest.mock
api.main
api.auth_dependencies

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Preserve the public health endpoint.
2. Preserve the public insurance prediction endpoint.
3. Test authenticated PDF uploads.
4. Validate PDF file restrictions.
5. Preserve multi-document answers and citations.
6. Test single-document question answering.
7. Verify user and session identity are forwarded correctly.
8. Verify error handling.

SECURITY NOTES
--------------
Only document endpoint tests receive a mocked authenticated user.

The dependency override is removed after each test.

Production JWT verification and session validation are unchanged.
Separate security tests verify unauthorized access.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.auth_dependencies import (
    AuthenticatedUser,
    get_current_user,
)
from api.main import app


# =============================================================================
# TEST CONFIGURATION
# =============================================================================

client = TestClient(app)

DOCUMENT_ID = "3feafa1c270f4fa7864412ddbc84c11c"

TEST_USER_ID = "00000000-0000-0000-0000-000000000011"
TEST_SESSION_ID = "00000000-0000-0000-0000-000000000022"


# =============================================================================
# AUTHENTICATED TEST FIXTURE
# =============================================================================

@pytest.fixture
def authenticated_client():
    """
    Provide an authenticated API client for document endpoint tests.

    This replaces the authentication dependency only for the
    duration of the individual test.

    It does not connect to PostgreSQL or create real sessions.
    """

    def fake_current_user():
        return AuthenticatedUser(
            user_id=TEST_USER_ID,
            session_id=TEST_SESSION_ID,
        )

    app.dependency_overrides[get_current_user] = fake_current_user

    try:
        yield client

    finally:
        app.dependency_overrides.pop(
            get_current_user,
            None,
        )


# =============================================================================
# PUBLIC ENDPOINT TESTS
# =============================================================================

def test_health_endpoint():
    """The health endpoint should remain publicly accessible."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@patch("api.main.predict_insurance_cost")
def test_predict_endpoint(mock_predict):
    """Prediction should pass customer data to the ML service."""
    mock_predict.return_value = 15000.0

    response = client.post(
        "/predict",
        json={
            "customer_data": {
                "age": 30,
            }
        },
    )

    assert response.status_code == 200

    assert (
        response.json()["estimated_insurance_cost"]
        == 15000.0
    )

    mock_predict.assert_called_once_with(
        {"age": 30}
    )


# =============================================================================
# AUTHENTICATED PDF UPLOAD TESTS
# =============================================================================

@patch("api.main.ingest_document")
def test_upload_document_success(
    mock_ingest,
    authenticated_client,
):
    """One valid PDF should be accepted and indexed."""
    mock_ingest.return_value = DOCUMENT_ID

    response = authenticated_client.post(
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

    assert (
        data["documents"][0]["document_id"]
        == DOCUMENT_ID
    )

    assert data["documents"][0]["status"] == "ready"

    mock_ingest.assert_called_once()

    arguments = mock_ingest.call_args.kwargs

    assert arguments["filename"] == "policy.pdf"
    assert arguments["user_id"] == TEST_USER_ID
    assert arguments["session_id"] == TEST_SESSION_ID


@patch("api.main.ingest_document")
def test_upload_two_documents(
    mock_ingest,
    authenticated_client,
):
    """Two PDFs should be processed in one upload request."""
    mock_ingest.side_effect = [
        DOCUMENT_ID,
        "1234567890abcdef1234567890abcdef",
    ]

    response = authenticated_client.post(
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

    for call in mock_ingest.call_args_list:
        assert call.kwargs["user_id"] == TEST_USER_ID
        assert call.kwargs["session_id"] == TEST_SESSION_ID


@patch("api.main.ingest_document")
def test_upload_rejects_non_pdf(
    mock_ingest,
    authenticated_client,
):
    """
    Invalid files should receive a per-file failure result.

    The existing batch endpoint returns HTTP 201 for a
    processed batch even when one file fails validation.
    """
    response = authenticated_client.post(
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

    assert (
        data["documents"][0]["status"]
        == "failed"
    )

    assert (
        "Only PDF files"
        in data["documents"][0]["error"]
    )

    mock_ingest.assert_not_called()


@patch("api.main.ingest_document")
def test_upload_rejects_duplicate_content(
    mock_ingest,
    authenticated_client,
):
    """Duplicate PDF content should be reported as a failure."""
    mock_ingest.side_effect = ValueError(
        "This PDF content is already indexed."
    )

    response = authenticated_client.post(
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

    assert (
        "already indexed"
        in data["documents"][0]["error"]
    )


@patch("api.main.ingest_document")
def test_upload_rejects_more_than_three_files(
    mock_ingest,
    authenticated_client,
):
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

    response = authenticated_client.post(
        "/documents",
        files=files,
    )

    assert response.status_code == 422

    mock_ingest.assert_not_called()


# =============================================================================
# MULTI-DOCUMENT QUESTION TEST
# =============================================================================

@patch("api.main.answer_multi_document_question")
def test_ask_multiple_documents(
    mock_answer,
    authenticated_client,
):
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

    response = authenticated_client.post(
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
        user_id=TEST_USER_ID,
        session_id=TEST_SESSION_ID,
    )


# =============================================================================
# SINGLE-DOCUMENT QUESTION TESTS
# =============================================================================

@patch("api.main.answer_indexed_document_question")
def test_ask_document_success(
    mock_answer,
    authenticated_client,
):
    """The single-document endpoint should return the service answer."""
    mock_answer.return_value = (
        "The waiting period is 24 months [E1]."
    )

    question = (
        "What is the waiting period for "
        "pre-existing conditions?"
    )

    response = authenticated_client.post(
        f"/documents/{DOCUMENT_ID}/ask",
        json={"question": question},
    )

    assert response.status_code == 200
    assert "24 months" in response.json()["answer"]

    mock_answer.assert_called_once_with(
        document_id=DOCUMENT_ID,
        question=question,
        user_id=TEST_USER_ID,
        session_id=TEST_SESSION_ID,
    )


@patch("api.main.answer_indexed_document_question")
def test_ask_document_invalid_id(
    mock_answer,
    authenticated_client,
):
    """Invalid document IDs should return HTTP 422."""
    mock_answer.side_effect = ValueError(
        "Invalid document ID."
    )

    response = authenticated_client.post(
        "/documents/invalid-id/ask",
        json={
            "question": "What is covered?",
        },
    )

    assert response.status_code == 422


@patch("api.main.answer_indexed_document_question")
def test_ask_document_service_failure(
    mock_answer,
    authenticated_client,
):
    """Unexpected service errors must not expose internal details."""
    mock_answer.side_effect = RuntimeError(
        "Internal service failure"
    )

    response = authenticated_client.post(
        f"/documents/{DOCUMENT_ID}/ask",
        json={
            "question": "What is covered?",
        },
    )

    assert response.status_code == 500

    assert response.json()["detail"] == (
        "Unable to answer the document question."
    )
