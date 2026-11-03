
"""
MODULE NAME
-----------
PHASE 4.4.7C MULTI-DOCUMENT RETRIEVAL REGRESSION TESTS

PURPOSE
-------
Verify bounded semantic retrieval, deterministic topic expansion,
authorization ordering, deduplication, and evidence selection.

ENVIRONMENT / CONFIGURATION
---------------------------
Run with pytest from the repository root.
No database, external API, or model download is required.

DEPENDENCIES
------------
pytest
unittest.mock
langchain_core
services.document_service

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Focused questions use semantic retrieval.
2. Multi-topic questions expand per policy.
3. Candidate search counts remain bounded.
4. Unauthorized documents fail before retrieval.
5. Retrieval never loads complete document collections.
6. The original question is preserved for reranking.
7. Unrecognized questions are not rewritten.
8. Focused evidence does not fill the context ceiling.
9. Multi-topic evidence remains bounded per topic and policy.
10. Duplicate passages do not consume multiple evidence positions.
11. Empty retrieval produces no fabricated evidence.
12. Missing reranked candidates do not crash selection.

SECURITY NOTES
--------------
Only fictional metadata and synthetic passages are used.
The undecorated retrieval function is called deliberately to isolate
retrieval behavior. Session locking and database ownership must be
verified separately in database-backed integration tests.
"""

from unittest.mock import patch

import pytest
from langchain_core.documents import Document

from services import document_service


POLICY_A = {
    "document_id": "policy-a",
    "filename": "policy-a.pdf",
    "collection_name": "collection-a",
    "status": "ready",
}

POLICY_B = {
    "document_id": "policy-b",
    "filename": "policy-b.pdf",
    "collection_name": "collection-b",
    "status": "ready",
}

USER_ID = "synthetic-user"
SESSION_ID = "synthetic-session"


def make_document(
    policy_id: str,
    chunk_id: int,
    text: str,
) -> Document:
    """Create a passage with stable synthetic metadata."""
    return Document(
        page_content=text,
        metadata={
            "document_id": policy_id,
            "chunk_id": chunk_id,
            "page": chunk_id + 1,
            "source": f"{policy_id}.pdf",
        },
    )


def fake_retrieve(metadata, question, candidate_k):
    """Return deterministic candidates without accessing ChromaDB."""
    policy_id = metadata["document_id"]

    if question == "waiting periods":
        topic = "waiting"
    elif question == "exclusions":
        topic = "exclusions"
    elif question == "copayments":
        topic = "copayment"
    else:
        topic = "original"

    topic_index = {
        "original": 0,
        "waiting": 1,
        "exclusions": 2,
        "copayment": 3,
    }[topic]

    return [
        make_document(
            policy_id,
            topic_index * 10 + index,
            f"{policy_id}: {topic} clause {index}",
        )
        for index in range(candidate_k)
    ]


def fake_rerank(question, documents, top_k):
    """Return deterministic order without loading a cross-encoder."""
    return documents[:top_k]


def execute_retrieval(
    question: str,
    metadata_list=None,
    retrieval_side_effect=fake_retrieve,
    rerank_side_effect=fake_rerank,
):
    """
    Exercise the undecorated retrieval implementation.

    This intentionally bypasses session_operation so these tests
    remain isolated from PostgreSQL and advisory-lock fixtures.
    """
    if metadata_list is None:
        metadata_list = [POLICY_A, POLICY_B]

    with (
        patch.object(
            document_service,
            "_resolve_documents",
            return_value=metadata_list,
        ) as resolve_mock,
        patch.object(
            document_service,
            "_retrieve_candidates",
            side_effect=retrieval_side_effect,
        ) as retrieve_mock,
        patch.object(
            document_service,
            "rerank_documents",
            side_effect=rerank_side_effect,
        ) as rerank_mock,
    ):
        result = (
            document_service.retrieve_multi_document_chunks.__wrapped__(
                question=question,
                document_ids=["synthetic-document"],
                user_id=USER_ID,
                session_id=SESSION_ID,
            )
        )

        return (
            result,
            resolve_mock,
            retrieve_mock,
            rerank_mock,
        )


def test_focused_question_uses_semantic_retrieval():
    """Focused questions search each policy once."""
    (documents, _), _, retrieve_mock, _ = execute_retrieval(
        "What is the deductible?"
    )

    assert retrieve_mock.call_count == 2
    assert documents
    assert all(isinstance(item, Document) for item in documents)


def test_multi_topic_query_expands_per_policy():
    """Two explicit topics produce original and topic searches."""
    _, _, retrieve_mock, _ = execute_retrieval(
        "Compare waiting periods and exclusions."
    )

    questions = [
        call.kwargs["question"]
        for call in retrieve_mock.call_args_list
    ]

    assert retrieve_mock.call_count == 6
    assert questions.count("waiting periods") == 2
    assert questions.count("exclusions") == 2


def test_semantic_results_are_bounded():
    """Every individual semantic search respects candidate limits."""
    _, _, retrieve_mock, _ = execute_retrieval(
        "Compare waiting periods, exclusions and copayments."
    )

    assert retrieve_mock.call_count == 8

    for call in retrieve_mock.call_args_list:
        assert call.kwargs["candidate_k"] <= 6


def test_unauthorized_document_fails_before_retrieval():
    """A failed authorization cannot trigger semantic retrieval."""
    with (
        patch.object(
            document_service,
            "_resolve_documents",
            side_effect=FileNotFoundError("Document not found."),
        ),
        patch.object(
            document_service,
            "_retrieve_candidates",
        ) as retrieve_mock,
    ):
        with pytest.raises(FileNotFoundError):
            document_service.retrieve_multi_document_chunks.__wrapped__(
                question="Compare deductibles.",
                document_ids=["unauthorized"],
                user_id=USER_ID,
                session_id=SESSION_ID,
            )

        retrieve_mock.assert_not_called()


def test_no_full_document_load():
    """The retrieval path uses bounded semantic searches only."""
    _, _, retrieve_mock, _ = execute_retrieval(
        "Summarize the selected policies."
    )

    assert retrieve_mock.call_count == 2

    for call in retrieve_mock.call_args_list:
        assert call.kwargs["candidate_k"] > 0
        assert call.kwargs["candidate_k"] <= 6


def test_original_question_is_preserved():
    """Reranking uses the complete original question."""
    original = "Compare waiting periods and exclusions."

    _, _, _, rerank_mock = execute_retrieval(original)

    assert rerank_mock.call_count == 1
    assert rerank_mock.call_args.kwargs["question"] == original


def test_unrecognized_question_is_not_rewritten():
    """Unrecognized intent does not create speculative searches."""
    _, _, retrieve_mock, _ = execute_retrieval(
        "Explain the unusual clause mentioned in my question."
    )

    assert retrieve_mock.call_count == 2


def test_focused_question_does_not_fill_context():
    """A focused comparison selects at most three passages per PDF."""
    (documents, _), _, _, _ = execute_retrieval(
        "What is the deductible?"
    )

    assert len(documents) == 6
    assert len(documents) < (
        document_service.MULTI_MAX_CONTEXT_CHUNKS
    )


def test_multi_topic_question_does_not_fill_context():
    """Three topics across two policies select at most 12 passages."""
    (documents, _), _, _, _ = execute_retrieval(
        "Compare waiting periods, exclusions and copayments."
    )

    assert len(documents) == 12
    assert len(documents) < (
        document_service.MULTI_MAX_CONTEXT_CHUNKS
    )


def test_duplicate_passages_are_selected_once():
    """Repeated semantic hits do not inflate evidence count."""
    repeated_by_policy = {}

    def retrieve_duplicates(metadata, question, candidate_k):
        policy_id = metadata["document_id"]

        if policy_id not in repeated_by_policy:
            repeated_by_policy[policy_id] = make_document(
                policy_id,
                1,
                "Repeated synthetic clause",
            )

        return [repeated_by_policy[policy_id]] * candidate_k

    (documents, _), _, _, _ = execute_retrieval(
        "Compare waiting periods and exclusions.",
        retrieval_side_effect=retrieve_duplicates,
    )

    assert len(documents) == 2
    assert len({
        document.metadata["document_id"]
        for document in documents
    }) == 2


def test_empty_retrieval_returns_no_evidence():
    """Empty semantic results must not fabricate evidence."""
    (documents, metadata), _, _, rerank_mock = execute_retrieval(
        "Compare waiting periods and exclusions.",
        retrieval_side_effect=lambda **kwargs: [],
    )

    assert documents == []
    assert len(metadata) == 2
    rerank_mock.assert_not_called()


def test_missing_reranked_candidates_are_ignored():
    """Selection tolerates a reranker returning fewer candidates."""
    def limited_reranker(question, documents, top_k):
        return documents[:1]

    (documents, _), _, _, _ = execute_retrieval(
        "Compare waiting periods and exclusions.",
        rerank_side_effect=limited_reranker,
    )

    assert len(documents) <= 1


def test_context_cap_is_enforced_with_five_policies():
    """The hard evidence ceiling holds for the maximum policy count."""
    policies = [
        {
            "document_id": f"policy-{index}",
            "filename": f"policy-{index}.pdf",
            "collection_name": f"collection-{index}",
            "status": "ready",
        }
        for index in range(5)
    ]

    (documents, _), _, retrieve_mock, _ = execute_retrieval(
        "Compare waiting periods, exclusions and copayments.",
        metadata_list=policies,
    )

    assert retrieve_mock.call_count == 20
    assert len(documents) <= 18