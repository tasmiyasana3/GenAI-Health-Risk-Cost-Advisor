
"""
MODULE NAME
-----------
DETERMINISTIC QUERY PLANNING UNIT TESTS

PURPOSE
-------
Verify bounded, predictable insurance-topic query planning.

ENVIRONMENT / CONFIGURATION
---------------------------
Run with pytest from the repository root.

DEPENDENCIES
------------
pytest
services.query_planning

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Preserve focused questions.
2. Expand explicitly multi-topic questions.
3. Preserve the original question during expansion.
4. Bound additional searches.
5. Avoid speculative expansion.
6. Reject invalid questions.

SECURITY NOTES
--------------
No database, vector store, credentials, or external APIs are used.
"""

import pytest

from services.query_planning import (
    MAX_EXPLICIT_TOPICS,
    build_retrieval_plan,
    plan_retrieval_queries,
)


def test_focused_question_is_not_expanded():
    question = "What is the annual deductible?"

    assert plan_retrieval_queries(question) == [question]


def test_two_topics_are_expanded():
    question = "Compare waiting periods and exclusions."

    assert plan_retrieval_queries(question) == [
        question,
        "waiting periods",
        "exclusions",
    ]


def test_original_question_is_preserved():
    question = (
        "Compare waiting periods, exclusions and copayments."
    )

    plan = build_retrieval_plan(question)

    assert plan.original_question == question
    assert plan.queries[0] == question
    assert plan.is_multi_topic


def test_expansion_is_bounded():
    question = (
        "Compare waiting periods, exclusions, copayments, "
        "deductibles and room rent limits."
    )

    plan = build_retrieval_plan(question)

    assert len(plan.queries) == 1 + MAX_EXPLICIT_TOPICS
    assert len(plan.topics) >= 4


def test_unrecognized_question_is_not_expanded():
    question = "Explain the unusual clause."

    assert plan_retrieval_queries(question) == [question]


def test_case_insensitive_topic_recognition():
    question = "Compare WAITING PERIODS and EXCLUSIONS."

    plan = build_retrieval_plan(question)

    assert plan.is_multi_topic
    assert "waiting periods" in plan.queries
    assert "exclusions" in plan.queries


@pytest.mark.parametrize(
    "question",
    ["", "   ", None, 123],
)
def test_invalid_questions_are_rejected(question):
    with pytest.raises(ValueError):
        build_retrieval_plan(question)