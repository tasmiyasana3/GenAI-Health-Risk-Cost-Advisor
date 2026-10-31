
"""
MODULE NAME
-----------
PHASE 4.4.6A - MULTI-USER SECURITY VERIFICATION

PURPOSE
-------
Verify authenticated API behavior for two users and three
independent login sessions.

ENVIRONMENT / CONFIGURATION
---------------------------
Run locally with pytest.

These are isolated API security tests. They do not connect to
PostgreSQL, ChromaDB, or Gemini.

DEPENDENCIES
------------
pytest
fastapi.testclient
unittest.mock
concurrent.futures
api.main
api.auth_dependencies

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Reject missing and inactive credentials.
2. Preserve independent user and session identities.
3. Enforce document ownership for metadata and deletion.
4. Reject unauthorized single-document retrieval.
5. Reject unauthorized multi-document comparisons.
6. Preserve session isolation during concurrent requests.

SECURITY NOTES
--------------
All identities, credentials, and document IDs are fictional.

The authentication dependency itself is not overridden.
JWT verification and session activity are mocked separately.

Document service mocks enforce an independent ownership
registry so API identity propagation can be tested.

Passing these tests does not replace real database and
vector-store integration verification.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import RLock
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from api.main import app


# ================================================================
# TEST IDENTITIES
# ================================================================

USER_A = "00000000-0000-0000-0000-000000000011"
USER_B = "00000000-0000-0000-0000-000000000012"

SESSION_A1 = "00000000-0000-0000-0000-000000000021"
SESSION_A2 = "00000000-0000-0000-0000-000000000022"
SESSION_B1 = "00000000-0000-0000-0000-000000000023"

DOCUMENT_A1 = "00000000000040008000000000000031"
DOCUMENT_A2 = "00000000000040008000000000000032"
DOCUMENT_B1 = "00000000000040008000000000000033"

IDENTITIES = {
    "token-a1": (USER_A, SESSION_A1),
    "token-a2": (USER_A, SESSION_A2),
    "token-b1": (USER_B, SESSION_B1),
}

OWNERS = {
    DOCUMENT_A1: (USER_A, SESSION_A1),
    DOCUMENT_A2: (USER_A, SESSION_A2),
    DOCUMENT_B1: (USER_B, SESSION_B1),
}


# ================================================================
# SHARED TEST STATE
# ================================================================

@pytest.fixture
def security_environment(monkeypatch):
    """
    Install fictional authentication and document records.

    A lock protects mutable test state so concurrent test requests
    can operate safely without introducing fixture races.
    """
    state_lock = RLock()

    active_sessions = set(IDENTITIES.values())
    documents = dict(OWNERS)

    def verify_token(token):
        """Simulate JWT claim verification, not authorization."""
        if token not in IDENTITIES:
            from services.token_service import TokenValidationError

            raise TokenValidationError("Invalid access token.")

        user_id, session_id = IDENTITIES[token]

        return {
            "user_id": user_id,
            "session_id": session_id,
        }

    def session_active(session_id, user_id):
        """Simulate the authoritative active-session lookup."""
        with state_lock:
            return (user_id, session_id) in active_sessions

    def get_document(document_id, user_id, session_id):
        """Return metadata only to the document's owner session."""
        with state_lock:
            owner = documents.get(document_id)

            if owner != (user_id, session_id):
                return None

            return {
                "document_id": document_id,
                "filename": "fictional_policy.pdf",
                "status": "ready",
            }

    def list_documents(user_id, session_id):
        """Return only documents belonging to this exact session."""
        with state_lock:
            matching_ids = [
                document_id
                for document_id, owner in documents.items()
                if owner == (user_id, session_id)
            ]

        return [
            {
                "document_id": document_id,
                "filename": "fictional_policy.pdf",
                "status": "ready",
            }
            for document_id in matching_ids
        ]

    def delete_document(document_id, user_id, session_id):
        """Reject deletion unless both ownership fields match."""
        with state_lock:
            if documents.get(document_id) != (user_id, session_id):
                return False

            del documents[document_id]
            return True

    def answer_single(document_id, question, user_id, session_id):
        """Reject unauthorized documents before generating an answer."""
        if get_document(document_id, user_id, session_id) is None:
            raise FileNotFoundError("Document not found.")

        return f"Authorized policy evidence for {document_id} [E1]."

    def answer_multiple(question, document_ids, user_id, session_id):
        """
        Authorize every selected document before returning evidence.

        This prevents a mixed authorized/unauthorized request from
        producing a partially leaked response.
        """
        with state_lock:
            for document_id in document_ids:
                if documents.get(document_id) != (user_id, session_id):
                    raise FileNotFoundError("Document not found.")

        return {
            "answer": "Authorized comparison [E1].",
            "citations": [
                {
                    "citation_id": f"E{index}",
                    "document_id": document_id,
                    "filename": "fictional_policy.pdf",
                    "page": 1,
                    "chunk_id": 0,
                    "excerpt": "Fictional insurance-policy evidence.",
                }
                for index, document_id in enumerate(
                    document_ids,
                    start=1,
                )
            ],
            "cited_evidence_ids": ["E1"] if document_ids else [],
            "citation_warning": None,
            "sources": [
                {
                    "document_id": document_id,
                    "filename": "fictional_policy.pdf",
                }
                for document_id in document_ids
            ],
        }

    # Patch the dependencies where the FastAPI application
    # actually imports and uses them.
    monkeypatch.setattr(
        "api.auth_dependencies.verify_access_token",
        verify_token,
    )

    monkeypatch.setattr(
        "api.auth_dependencies.is_session_active",
        session_active,
    )

    monkeypatch.setattr(
        "api.main.get_document_metadata",
        get_document,
    )

    monkeypatch.setattr(
        "api.main.list_indexed_documents",
        list_documents,
    )

    monkeypatch.setattr(
        "api.main.delete_indexed_document",
        delete_document,
    )

    monkeypatch.setattr(
        "api.main.answer_indexed_document_question",
        answer_single,
    )

    monkeypatch.setattr(
        "api.main.answer_multi_document_question",
        answer_multiple,
    )

    return {
        "lock": state_lock,
        "active_sessions": active_sessions,
        "documents": documents,
    }


def make_client(token=None):
    """Create an independent HTTP client with optional Bearer token."""
    headers = {}

    if token is not None:
        headers["Authorization"] = f"Bearer {token}"

    return TestClient(app, headers=headers)


# ================================================================
# STAGE 1 - AUTHENTICATION AND SESSION INDEPENDENCE
# ================================================================

def test_missing_token_is_rejected(security_environment):
    """Protected endpoints must not accept anonymous requests."""
    with make_client() as client:
        response = client.get("/documents")

    assert response.status_code == 401


def test_invalid_token_is_rejected(security_environment):
    """Unknown Bearer credentials must not establish identity."""
    with make_client("invalid-token") as client:
        response = client.get("/documents")

    assert response.status_code == 401


@pytest.mark.parametrize(
    "token,expected_document",
    [
        ("token-a1", DOCUMENT_A1),
        ("token-a2", DOCUMENT_A2),
        ("token-b1", DOCUMENT_B1),
    ],
)
def test_independent_sessions(
    security_environment,
    token,
    expected_document,
):
    """Each active session sees only its own document registry."""
    with make_client(token) as client:
        response = client.get("/documents")

    assert response.status_code == 200

    actual_ids = {
        item["document_id"]
        for item in response.json()["documents"]
    }

    assert actual_ids == {expected_document}


# ================================================================
# STAGE 2 - DOCUMENT OWNERSHIP AND AUTHORIZATION
# ================================================================

@pytest.mark.parametrize(
    "token,foreign_document",
    [
        ("token-a1", DOCUMENT_A2),
        ("token-a1", DOCUMENT_B1),
        ("token-a2", DOCUMENT_A1),
        ("token-b1", DOCUMENT_A1),
    ],
)
def test_foreign_document_metadata_is_hidden(
    security_environment,
    token,
    foreign_document,
):
    """Both cross-user and cross-session metadata access fail."""
    with make_client(token) as client:
        response = client.get(
            f"/documents/{foreign_document}"
        )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "token,foreign_document",
    [
        ("token-a1", DOCUMENT_A2),
        ("token-a1", DOCUMENT_B1),
        ("token-b1", DOCUMENT_A1),
    ],
)
def test_foreign_document_cannot_be_deleted(
    security_environment,
    token,
    foreign_document,
):
    """Unauthorized deletion must not modify document ownership."""
    with make_client(token) as client:
        response = client.delete(
            f"/documents/{foreign_document}"
        )

    assert response.status_code == 404
    assert foreign_document in security_environment["documents"]


def test_owner_can_delete_own_document(security_environment):
    """Authorized deletion affects only the selected document."""
    with make_client("token-a1") as client:
        response = client.delete(
            f"/documents/{DOCUMENT_A1}"
        )

    assert response.status_code == 200
    assert DOCUMENT_A1 not in security_environment["documents"]
    assert DOCUMENT_A2 in security_environment["documents"]
    assert DOCUMENT_B1 in security_environment["documents"]


# ================================================================
# STAGE 3 - RETRIEVAL AND CITATION ISOLATION
# ================================================================

def test_foreign_document_question_is_rejected(
    security_environment,
):
    """A user cannot ask questions about another user's policy."""
    with make_client("token-a1") as client:
        response = client.post(
            f"/documents/{DOCUMENT_B1}/ask",
            json={"question": "What is covered?"},
        )

    assert response.status_code == 404


def test_cross_session_question_is_rejected(
    security_environment,
):
    """Two sessions belonging to one user remain isolated."""
    with make_client("token-a2") as client:
        response = client.post(
            f"/documents/{DOCUMENT_A1}/ask",
            json={"question": "What is covered?"},
        )

    assert response.status_code == 404


def test_unauthorized_multi_document_comparison_is_rejected(
    security_environment,
):
    """Mixed authorized and foreign documents must fail together."""
    with make_client("token-a1") as client:
        response = client.post(
            "/documents/ask",
            json={
                "question": "Compare the waiting periods.",
                "document_ids": [DOCUMENT_A1, DOCUMENT_B1],
            },
        )

    assert response.status_code == 404


def test_authorized_citations_reference_only_selected_document(
    security_environment,
):
    """Returned citation metadata must identify authorized evidence."""
    with make_client("token-a1") as client:
        response = client.post(
            "/documents/ask",
            json={
                "question": "What is the waiting period?",
                "document_ids": [DOCUMENT_A1],
            },
        )

    assert response.status_code == 200

    result = response.json()

    citation_ids = {
        citation["document_id"]
        for citation in result["citations"]
    }

    source_ids = {
        source["document_id"]
        for source in result["sources"]
    }

    assert citation_ids == {DOCUMENT_A1}
    assert source_ids == {DOCUMENT_A1}


# ================================================================
# STAGE 4 - SESSION REVOCATION ISOLATION
# ================================================================

def test_revoking_one_session_preserves_others(
    security_environment,
):
    """Revoking A1 must not revoke A2 or B1."""
    with security_environment["lock"]:
        security_environment["active_sessions"].remove(
            (USER_A, SESSION_A1)
        )

    expected_status = {
        "token-a1": 401,
        "token-a2": 200,
        "token-b1": 200,
    }

    for token, status in expected_status.items():
        with make_client(token) as client:
            response = client.get("/documents")

        assert response.status_code == status


def test_revoked_session_cannot_access_its_old_document(
    security_environment,
):
    """A previously valid access token loses access after revocation."""
    with security_environment["lock"]:
        security_environment["active_sessions"].remove(
            (USER_A, SESSION_A1)
        )

    with make_client("token-a1") as client:
        response = client.get(
            f"/documents/{DOCUMENT_A1}"
        )

    assert response.status_code == 401


# ================================================================
# STAGE 5 - CONCURRENT REQUEST ISOLATION
# ================================================================

def test_concurrent_users_receive_only_their_documents(
    security_environment,
):
    """Concurrent requests must not mix user or session identity."""

    requests = [
        ("token-a1", DOCUMENT_A1),
        ("token-a2", DOCUMENT_A2),
        ("token-b1", DOCUMENT_B1),
    ] * 5

    def request_documents(item):
        token, expected_document = item

        with make_client(token) as client:
            response = client.get("/documents")

        assert response.status_code == 200

        document_ids = {
            document["document_id"]
            for document in response.json()["documents"]
        }

        return document_ids == {expected_document}

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(request_documents, requests))

    assert all(results)


def test_concurrent_foreign_deletion_attempts_fail(
    security_environment,
):
    """Parallel unauthorized deletions cannot remove an owned policy."""

    attempts = [
        ("token-a2", DOCUMENT_A1),
        ("token-b1", DOCUMENT_A1),
        ("token-a1", DOCUMENT_B1),
    ] * 4

    def attempt_deletion(item):
        token, document_id = item

        with make_client(token) as client:
            response = client.delete(
                f"/documents/{document_id}"
            )

        return response.status_code

    with ThreadPoolExecutor(max_workers=3) as executor:
        statuses = list(executor.map(attempt_deletion, attempts))

    assert all(status == 404 for status in statuses)

    assert DOCUMENT_A1 in security_environment["documents"]
    assert DOCUMENT_B1 in security_environment["documents"]
