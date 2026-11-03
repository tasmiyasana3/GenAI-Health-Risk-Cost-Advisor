"""
MODULE NAME
-----------
PHASE 4.4.7C TOPIC-BY-POLICY COVERAGE TESTS

PURPOSE
-------
Evaluate whether selected evidence contains the expected
topic-specific passages for every selected insurance policy.

ENVIRONMENT / CONFIGURATION
---------------------------
Python 3.11+.
Run through pytest from the repository root.
No external API calls are required.

DEPENDENCIES
------------
pytest
langchain_core
services.document_service

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Detect missing expected evidence.
2. Distinguish policy representation from actual topic coverage.
3. Detect incomplete multi-topic retrieval.
4. Reject duplicate evidence as additional coverage.
5. Verify complete coverage for labeled synthetic examples.

SECURITY NOTES
--------------
All evidence is synthetic.
No real patient information, credentials, databases,
or external LLM services are used.

These tests evaluate the coverage metric, not the real
embedding model or production retrieval accuracy.
"""

from dataclasses import dataclass

from langchain_core.documents import Document


@dataclass(frozen=True)
class ExpectedEvidence:
    """One expected policy-topic-passage combination."""

    policy_id: str
    topic: str
    chunk_id: int


def make_document(
    policy_id: str,
    chunk_id: int,
    text: str,
) -> Document:
    """Construct synthetic evidence with stable identifiers."""
    return Document(
        page_content=text,
        metadata={
            "document_id": policy_id,
            "chunk_id": chunk_id,
            "page": chunk_id + 1,
            "source": f"{policy_id}.pdf",
        },
    )


def calculate_topic_coverage(
    retrieved: list[Document],
    expected: list[ExpectedEvidence],
) -> dict:
    """
    Measure labeled evidence coverage.

    This is an exact chunk-identity evaluation.

    It must not be confused with semantic relevance scoring:
    the expected chunk IDs must be independently labeled.
    """
    retrieved_keys = {
        (
            document.metadata.get("document_id"),
            document.metadata.get("chunk_id"),
        )
        for document in retrieved
    }

    total = len(expected)
    matched = []

    missing = []

    for item in expected:
        key = (item.policy_id, item.chunk_id)

        if key in retrieved_keys:
            matched.append(item)
        else:
            missing.append(item)

    coverage = len(matched) / total if total else 1.0

    topic_policy_status = {}

    for item in expected:
        key = (item.policy_id, item.topic)

        topic_policy_status.setdefault(key, True)

        if item in missing:
            topic_policy_status[key] = False

    return {
        "expected_count": total,
        "matched_count": len(matched),
        "coverage": coverage,
        "missing": missing,
        "topic_policy_status": topic_policy_status,
    }


def expected_comparison_evidence() -> list[ExpectedEvidence]:
    """Return independently specified synthetic gold labels."""
    return [
        ExpectedEvidence("policy-a", "waiting", 1),
        ExpectedEvidence("policy-a", "exclusions", 2),
        ExpectedEvidence("policy-a", "copayment", 3),
        ExpectedEvidence("policy-b", "waiting", 1),
        ExpectedEvidence("policy-b", "exclusions", 2),
        ExpectedEvidence("policy-b", "copayment", 3),
    ]


def test_complete_labeled_coverage():
    """Every expected passage should be accounted for."""
    retrieved = [
        make_document(policy, index, "Synthetic clause")
        for policy in ("policy-a", "policy-b")
        for index in (1, 2, 3)
    ]

    result = calculate_topic_coverage(
        retrieved,
        expected_comparison_evidence(),
    )

    assert result["coverage"] == 1.0
    assert result["matched_count"] == 6
    assert result["missing"] == []
    assert all(result["topic_policy_status"].values())


def test_policy_presence_does_not_imply_topic_coverage():
    """A represented policy may still lack required clauses."""
    retrieved = [
        make_document("policy-a", 1, "Waiting period"),
        make_document("policy-b", 1, "Waiting period"),
    ]

    result = calculate_topic_coverage(
        retrieved,
        expected_comparison_evidence(),
    )

    assert result["coverage"] == 2 / 6
    assert result["matched_count"] == 2
    assert len(result["missing"]) == 4

    assert result["topic_policy_status"][
        ("policy-a", "waiting")
    ]

    assert not result["topic_policy_status"][
        ("policy-a", "exclusions")
    ]


def test_duplicate_passages_do_not_increase_coverage():
    """Repeated evidence cannot replace missing topic evidence."""
    repeated = make_document(
        "policy-a",
        1,
        "Waiting period",
    )

    result = calculate_topic_coverage(
        [repeated, repeated, repeated],
        expected_comparison_evidence(),
    )

    assert result["matched_count"] == 1
    assert result["coverage"] == 1 / 6


def test_empty_retrieval_has_zero_coverage():
    """Missing evidence must not be counted as covered."""
    result = calculate_topic_coverage(
        [],
        expected_comparison_evidence(),
    )

    assert result["coverage"] == 0.0
    assert len(result["missing"]) == 6


def test_empty_gold_set_is_explicitly_handled():
    """An empty reference set has no missing labeled passages."""
    result = calculate_topic_coverage([], [])

    assert result["expected_count"] == 0
    assert result["coverage"] == 1.0
    assert result["topic_policy_status"] == {}