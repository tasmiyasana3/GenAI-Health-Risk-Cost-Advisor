
"""
MODULE NAME
-----------
PHASE 4.4.7B - OFFLINE ANSWER AND CITATION REVIEW

PURPOSE
-------
Validate and summarize manually reviewed RAG answer quality.

ENVIRONMENT / CONFIGURATION
---------------------------
Run locally with --questions and --reviews JSON files.
No model or database configuration is required.

DEPENDENCIES
------------
Python standard library only.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Validate review IDs and expected fact coverage.
2. Count supported and unsupported expected facts.
3. Summarize answer correctness and citation faithfulness.
4. Report missing reviews without silently scoring them as failures.

SECURITY NOTES
--------------
Use only fictional policies and reviewed evidence.
Do not store private policy text, authentication tokens, or secrets.
Scores reflect human judgements, not automatic semantic verification.
"""

import argparse
import json
from pathlib import Path
from typing import Any


# =============================================================================
# DATA LOADING
# =============================================================================

def read_json(path: Path) -> Any:
    """Read a JSON file with a clear error for invalid content."""
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read {path}: {error}") from error


# =============================================================================
# REVIEW VALIDATION AND SCORING
# =============================================================================

def summarize_reviews(
    questions: Any,
    reviews: Any,
) -> dict[str, Any]:
    """Summarize explicit reviewer decisions for each evaluation case."""
    if not isinstance(questions, list) or not questions:
        raise ValueError("Questions must be a nonempty list.")

    if not isinstance(reviews, list):
        raise ValueError("Reviews must be a list.")

    cases = {}

    for case in questions:
        if not isinstance(case, dict) or not isinstance(
            case.get("id"), str
        ):
            raise ValueError("Invalid question record.")

        if case["id"] in cases:
            raise ValueError("Duplicate question ID.")

        cases[case["id"]] = case

    reviewed_ids = set()
    passed_facts = 0
    total_facts = 0
    supported_citations = 0
    total_citations = 0
    passed_behavior = 0
    per_case = []

    for review in reviews:
        if not isinstance(review, dict):
            raise ValueError("Review must be an object.")

        case_id = review.get("id")

        if case_id not in cases or case_id in reviewed_ids:
            raise ValueError(f"Unknown or duplicate review: {case_id}")

        reviewed_ids.add(case_id)

        fact_results = review.get("fact_correct")
        citation_results = review.get("citation_supported")
        behavior_correct = review.get("behavior_correct")

        expected_facts = cases[case_id].get("expected_facts", [])

        if (
            not isinstance(fact_results, list)
            or len(fact_results) != len(expected_facts)
            or any(type(value) is not bool for value in fact_results)
        ):
            raise ValueError(
                f"{case_id}: provide one boolean per expected fact."
            )

        if (
            not isinstance(citation_results, list)
            or any(type(value) is not bool for value in citation_results)
        ):
            raise ValueError(
                f"{case_id}: citation_supported must be booleans."
            )

        if type(behavior_correct) is not bool:
            raise ValueError(
                f"{case_id}: behavior_correct must be boolean."
            )

        fact_passes = sum(fact_results)
        citation_passes = sum(citation_results)

        passed_facts += fact_passes
        total_facts += len(fact_results)
        supported_citations += citation_passes
        total_citations += len(citation_results)
        passed_behavior += int(behavior_correct)

        per_case.append({
            "id": case_id,
            "correct_facts": fact_passes,
            "total_facts": len(fact_results),
            "supported_citations": citation_passes,
            "reviewed_citations": len(citation_results),
            "behavior_correct": behavior_correct,
        })

    def ratio(numerator: int, denominator: int) -> float | None:
        """Return no score when the denominator is zero."""
        if denominator == 0:
            return None
        return round(numerator / denominator, 4)

    return {
        "total_cases": len(cases),
        "reviewed_cases": len(reviewed_ids),
        "missing_case_ids": sorted(set(cases) - reviewed_ids),
        "expected_fact_accuracy": ratio(passed_facts, total_facts),
        "citation_support_rate": ratio(
            supported_citations,
            total_citations,
        ),
        "expected_behavior_accuracy": ratio(
            passed_behavior,
            len(reviewed_ids),
        ),
        "per_case": per_case,
        "limitations": [
            "Results depend on explicit human review.",
            "Fact accuracy covers labelled facts, not every answer claim.",
            "Citation support requires checking cited passage content.",
            "Unreviewed cases are excluded from calculated rates.",
        ],
    }


# =============================================================================
# COMMAND-LINE INTERFACE
# =============================================================================

def main() -> int:
    """Validate review records and print a JSON summary."""
    parser = argparse.ArgumentParser(
        description="Summarize manually reviewed RAG answers."
    )

    parser.add_argument(
        "--questions",
        type=Path,
        default=Path(__file__).resolve().parent
        / "phase447_questions.json",
    )

    parser.add_argument(
        "--reviews",
        type=Path,
        required=True,
    )

    args = parser.parse_args()

    try:
        report = summarize_reviews(
            read_json(args.questions),
            read_json(args.reviews),
        )
    except ValueError as error:
        parser.exit(1, f"Review error: {error}\n")

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())