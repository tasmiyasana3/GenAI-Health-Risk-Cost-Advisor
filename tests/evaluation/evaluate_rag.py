
"""
MODULE NAME
-----------
PHASE 4.4.7B - OFFLINE RAG RETRIEVAL EVALUATOR

PURPOSE
-------
Validate labelled insurance-policy evaluation cases and calculate
page-level retrieval quality from previously captured retrieval results.

This module separates retrieval evaluation from live RAG execution.
It does not invoke an LLM or retrieve documents itself.

ENVIRONMENT / CONFIGURATION
---------------------------
Run from the repository root using Python 3.11 or newer.

Default ground-truth file:
tests/evaluation/phase447_questions.json

Use --validate-only to check ground truth without retrieval results.
Use --results to evaluate a separate JSON file containing retrieved
policy/page references.

No environment variables, API keys, or database connections are needed.

DEPENDENCIES
------------
Python standard library only:
argparse, json, pathlib, collections, and typing.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Validate case IDs, questions, expected facts, and evidence labels.
2. Validate retrieved policy/page references.
3. Calculate page-level Hit@k, Precision@k, Recall@k, and MRR@k.
4. Report per-question and macro-average retrieval metrics.
5. Reject malformed or duplicate retrieval records.
6. Keep missing retrieval results distinct from failed retrievals.

SECURITY NOTES
--------------
This evaluator is offline and read-only.

It does not access authentication tokens, private documents,
PostgreSQL, ChromaDB, or the Gemini API.

Use fictional policy references only in evaluation input files.
Never include user identifiers, secrets, or private document text.

Page-level relevance is a proxy for evidence retrieval quality.
It does not establish answer correctness or citation faithfulness.
"""

# =============================================================================
# IMPORTS AND DEFAULT PATHS
# =============================================================================

import argparse
import json
from pathlib import Path
from typing import Any


EVALUATION_DIRECTORY = Path(__file__).resolve().parent

DEFAULT_QUESTIONS_PATH = (
    EVALUATION_DIRECTORY / "phase447_questions.json"
)

REQUIRED_CASE_FIELDS = {
    "id",
    "category",
    "question",
    "expected_behavior",
    "expected_facts",
    "expected_evidence",
}


# =============================================================================
# JSON LOADING AND VALIDATION HELPERS
# =============================================================================

def load_json(path: Path) -> Any:
    """Read a JSON file and report useful file or syntax errors."""
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError as error:
        raise ValueError(
            f"JSON file does not exist: {path}"
        ) from error
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid JSON in {path}: {error}"
        ) from error


def validate_policy_page(
    reference: dict[str, Any],
    *,
    allow_multiple_pages: bool,
) -> None:
    """Validate a fictional policy reference and its page numbers."""
    if not isinstance(reference, dict):
        raise ValueError("Evidence reference must be an object.")

    policy = reference.get("policy")

    if not isinstance(policy, str) or not policy.strip():
        raise ValueError("Evidence policy must be a nonempty string.")

    if allow_multiple_pages:
        pages = reference.get("pages")

        if not isinstance(pages, list) or not pages:
            raise ValueError(
                "Expected evidence must contain a nonempty pages list."
            )

        if any(
            type(page) is not int or page < 1
            for page in pages
        ):
            raise ValueError(
                "Expected page numbers must be positive integers."
            )

        if len(set(pages)) != len(pages):
            raise ValueError("Expected pages must not repeat.")
    else:
        page = reference.get("page")

        if type(page) is not int or page < 1:
            raise ValueError(
                "Retrieved page must be a positive integer."
            )


def validate_questions(data: Any) -> list[dict[str, Any]]:
    """Validate labelled cases and reject duplicate identifiers."""
    if not isinstance(data, list) or not data:
        raise ValueError("Questions must be a nonempty JSON array.")

    seen_ids: set[str] = set()

    for case in data:
        if not isinstance(case, dict):
            raise ValueError("Each evaluation case must be an object.")

        missing = REQUIRED_CASE_FIELDS - case.keys()

        if missing:
            raise ValueError(
                f"Evaluation case is missing fields: {sorted(missing)}"
            )

        case_id = case["id"]

        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError("Case ID must be a nonempty string.")

        if case_id in seen_ids:
            raise ValueError(f"Duplicate case ID: {case_id}")

        seen_ids.add(case_id)

        for field in ("question", "category"):
            value = case[field]

            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"{case_id}: {field} must be a nonempty string."
                )

        if case["expected_behavior"] not in {"answer", "abstain"}:
            raise ValueError(
                f"{case_id}: unsupported expected_behavior."
            )

        facts = case["expected_facts"]
        evidence = case["expected_evidence"]

        if not isinstance(facts, list) or not facts:
            raise ValueError(
                f"{case_id}: expected_facts must be nonempty."
            )

        for fact in facts:
            if (
                not isinstance(fact, dict)
                or not isinstance(fact.get("policy"), str)
                or not fact["policy"].strip()
                or not isinstance(fact.get("fact"), str)
                or not fact["fact"].strip()
            ):
                raise ValueError(
                    f"{case_id}: invalid expected fact."
                )

        if not isinstance(evidence, list) or not evidence:
            raise ValueError(
                f"{case_id}: expected_evidence must be nonempty."
            )

        seen_policies: set[str] = set()

        for reference in evidence:
            validate_policy_page(
                reference,
                allow_multiple_pages=True,
            )

            policy = reference["policy"]

            if policy in seen_policies:
                raise ValueError(
                    f"{case_id}: duplicate evidence policy {policy}."
                )

            seen_policies.add(policy)

        fact_policies = {fact["policy"] for fact in facts}

        if fact_policies != seen_policies:
            raise ValueError(
                f"{case_id}: fact and evidence policies differ."
            )

    return data


def validate_results(
    data: Any,
    known_ids: set[str],
) -> dict[str, list[dict[str, Any]]]:
    """Validate results and map each case ID to ranked evidence."""
    if not isinstance(data, list):
        raise ValueError("Results must be a JSON array.")

    results: dict[str, list[dict[str, Any]]] = {}

    for record in data:
        if not isinstance(record, dict):
            raise ValueError("Each result must be an object.")

        case_id = record.get("id")

        if not isinstance(case_id, str) or case_id not in known_ids:
            raise ValueError(
                f"Unknown or invalid result case ID: {case_id}"
            )

        if case_id in results:
            raise ValueError(
                f"Duplicate retrieval result: {case_id}"
            )

        retrieved = record.get("retrieved")

        if not isinstance(retrieved, list):
            raise ValueError(
                f"{case_id}: retrieved must be an array."
            )

        for reference in retrieved:
            validate_policy_page(
                reference,
                allow_multiple_pages=False,
            )

        results[case_id] = retrieved

    return results


# =============================================================================
# PAGE-LEVEL RETRIEVAL SCORING
# =============================================================================

def score_case(
    case: dict[str, Any],
    retrieved: list[dict[str, Any]],
    k: int,
) -> dict[str, Any]:
    """
    Score ranked results against expected policy/page evidence.

    Each expected policy is treated as one evidence group. Any page
    listed for that policy can satisfy that group's page-level match.

    A group can be recalled only once. Duplicate retrieved pages
    therefore cannot inflate recall.

    Precision counts retrieved references that match an expected
    policy and one of its acceptable pages.

    This is intentionally a page-level proxy, not passage-level
    semantic relevance.
    """
    expected = {
        item["policy"]: set(item["pages"])
        for item in case["expected_evidence"]
    }

    top_results = retrieved[:k]

    matched_policies: set[str] = set()
    relevant_count = 0
    first_relevant_rank: int | None = None
    seen_references: set[tuple[str, int]] = set()

    for rank, item in enumerate(top_results, start=1):
        reference = (item["policy"], item["page"])

        # Repeated references should not receive extra credit.
        if reference in seen_references:
            continue

        seen_references.add(reference)

        policy, page = reference

        if policy in expected and page in expected[policy]:
            relevant_count += 1
            matched_policies.add(policy)

            if first_relevant_rank is None:
                first_relevant_rank = rank

    expected_count = len(expected)

    # Precision uses the number of returned results, up to k.
    # Empty retrieval is scored as zero rather than dividing by zero.
    precision = (
        relevant_count / len(top_results)
        if top_results else 0.0
    )

    recall = len(matched_policies) / expected_count

    reciprocal_rank = (
        1.0 / first_relevant_rank
        if first_relevant_rank is not None else 0.0
    )

    return {
        "id": case["id"],
        "category": case["category"],
        "expected_behavior": case["expected_behavior"],
        "retrieved_count": len(retrieved),
        "evaluated_count": len(top_results),
        "expected_policy_groups": expected_count,
        "matched_policy_groups": len(matched_policies),
        "hit_at_k": int(bool(matched_policies)),
        "precision_at_k": round(precision, 4),
        "recall_at_k": round(recall, 4),
        "mrr_at_k": round(reciprocal_rank, 4),
    }


def evaluate(
    questions: list[dict[str, Any]],
    results: dict[str, list[dict[str, Any]]],
    k: int,
) -> dict[str, Any]:
    """Calculate per-case and macro-average retrieval metrics."""
    scored = [
        score_case(case, results[case["id"]], k)
        for case in questions
        if case["id"] in results
    ]

    metrics = (
        "hit_at_k",
        "precision_at_k",
        "recall_at_k",
        "mrr_at_k",
    )

    macro = {
        metric: round(
            sum(item[metric] for item in scored) / len(scored),
            4,
        )
        for metric in metrics
    } if scored else {}

    missing_ids = [
        case["id"]
        for case in questions
        if case["id"] not in results
    ]

    return {
        "evaluation_level": "page",
        "k": k,
        "total_cases": len(questions),
        "evaluated_cases": len(scored),
        "missing_case_ids": missing_ids,
        "macro_average": macro,
        "per_case": scored,
        "limitations": [
            "Page matches do not prove passage-level relevance.",
            "Each expected policy is one recall group.",
            "Multiple acceptable pages within one policy are alternatives.",
            "MRR measures the first relevant result, not full coverage.",
            "Answer correctness and citation faithfulness are not scored.",
            "Missing cases are excluded from macro averages.",
        ],
    }


# =============================================================================
# COMMAND-LINE ENTRY POINT
# =============================================================================

def main() -> int:
    """Validate ground truth or evaluate captured retrieval results."""
    parser = argparse.ArgumentParser(
        description="Offline Phase 4.4.7B retrieval evaluator."
    )

    parser.add_argument(
        "--questions",
        type=Path,
        default=DEFAULT_QUESTIONS_PATH,
        help="Path to labelled evaluation questions.",
    )

    parser.add_argument(
        "--results",
        type=Path,
        help="Path to captured retrieval results JSON.",
    )

    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate ground truth without scoring retrieval.",
    )

    parser.add_argument(
        "--k",
        type=int,
        default=6,
        help="Maximum ranked results to evaluate (default: 6).",
    )

    args = parser.parse_args()

    if args.k < 1:
        parser.error("--k must be at least 1.")

    try:
        questions = validate_questions(
            load_json(args.questions)
        )

        if args.validate_only:
            print(
                f"PASS: {len(questions)} evaluation cases validated."
            )
            return 0

        if args.results is None:
            parser.error(
                "Provide --results or use --validate-only."
            )

        known_ids = {case["id"] for case in questions}

        results = validate_results(
            load_json(args.results),
            known_ids,
        )

        report = evaluate(questions, results, args.k)

        print(json.dumps(report, indent=2))

        return 0

    except ValueError as error:
        parser.exit(
            status=1,
            message=f"Evaluation error: {error}\n",
        )


if __name__ == "__main__":
    raise SystemExit(main())
