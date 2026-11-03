
"""
MODULE NAME
-----------
DETERMINISTIC INSURANCE QUERY PLANNING

PURPOSE
-------
Identify explicitly requested insurance topics for bounded semantic
retrieval without relying on an external language model.

ENVIRONMENT / CONFIGURATION
---------------------------
Python 3.11+. No credentials or external API configuration required.

DEPENDENCIES
------------
Python standard library.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Preserve the original user question.
2. Recognize explicitly mentioned insurance concepts.
3. Expand questions containing multiple supported topics.
4. Bound the number of additional semantic searches.
5. Avoid unnecessary expansion of focused or unsupported questions.

SECURITY NOTES
--------------
This module does not access documents, databases, sessions, or secrets.
It never sends question text to an external query-rewriting service.
Document authorization remains the responsibility of document_service.
"""

import re
from dataclasses import dataclass


MAX_EXPLICIT_TOPICS = 3


TOPIC_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "waiting periods",
        r"\b(waiting\s+periods?|waiting\s+time)\b",
    ),
    (
        "exclusions",
        r"\b(exclusions?|not\s+covered|excluded)\b",
    ),
    (
        "copayments",
        r"\b(co[ -]?payments?|co[ -]?pays?)\b",
    ),
    (
        "deductibles",
        r"\b(deductibles?)\b",
    ),
    (
        "room rent limits",
        r"\b(room[ -]?rent|room\s+limits?)\b",
    ),
    (
        "claim deadlines",
        r"\b(claim\s+(?:deadlines?|timelines?|submission)|"
        r"filing\s+deadlines?)\b",
    ),
    (
        "coverage benefits",
        r"\b(benefits?|coverage|covered\s+services?)\b",
    ),
    (
        "sum insured",
        r"\b(sum\s+insured|coverage\s+amounts?)\b",
    ),
)


@dataclass(frozen=True)
class RetrievalPlan:
    """Immutable plan for one original user question."""

    original_question: str
    topics: tuple[str, ...]

    @property
    def queries(self) -> tuple[str, ...]:
        """Return the original question and bounded topic searches."""
        if len(self.topics) < 2:
            return (self.original_question,)

        return (
            self.original_question,
            *self.topics[:MAX_EXPLICIT_TOPICS],
        )

    @property
    def is_multi_topic(self) -> bool:
        """Identify questions receiving explicit topic expansion."""
        return len(self.queries) > 1


def build_retrieval_plan(question: str) -> RetrievalPlan:
    """
    Create a deterministic retrieval plan.

    Topic recognition is based on the original question, not on
    generated guesses about what a policy might contain.

    When more than three topics are mentioned, only the first three
    recognized topics receive dedicated searches. The original
    question still contains the complete user request.
    """
    if not isinstance(question, str) or not question.strip():
        raise ValueError("Question cannot be empty.")

    original_question = question.strip()

    detected_topics = tuple(
        topic
        for topic, pattern in TOPIC_PATTERNS
        if re.search(
            pattern,
            original_question,
            re.IGNORECASE,
        )
    )

    return RetrievalPlan(
        original_question=original_question,
        topics=detected_topics,
    )


def plan_retrieval_queries(question: str) -> list[str]:
    """
    Preserve the existing public interface for retrieval callers.

    The returned list always begins with the original question.
    """
    return list(build_retrieval_plan(question).queries)