
"""
MODULE NAME
-----------
PHASE 4.4.7B - RETRIEVAL EVALUATOR UNIT TESTS

PURPOSE
-------
Verify the offline page-level retrieval evaluator.

ENVIRONMENT / CONFIGURATION
---------------------------
Run with pytest from the repository root. No environment secrets needed.

DEPENDENCIES
------------
pytest and tests/evaluation/evaluate_rag.py.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
Validate labelled cases, result structure, ranking metrics,
missing cases, duplicates, and zero-result behavior.

SECURITY NOTES
--------------
All data is synthetic. No API, database, or network access is needed.
"""

import importlib.util
from pathlib import Path

import pytest


# =============================================================================
# LOAD THE STANDALONE EVALUATOR WITHOUT MODIFYING APPLICATION SERVICES
# =============================================================================

EVALUATOR_PATH = (
    Path(__file__).resolve().parents[1]
    / "evaluation"
    / "evaluate_rag.py"
)

spec = importlib.util.spec_from_file_location(
    "phase447_offline_evaluator",
    EVALUATOR_PATH,
)
assert spec is not None and spec.loader is not None

evaluator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluator)


# =============================================================================
# SYNTHETIC TEST FIXTURES
# =============================================================================

@pytest.fixture
def example_case():
    """Return one question requiring evidence from two policies."""
    return {
        "id": "test_deductible",
        "category": "policy_comparison",
        "question": "Compare the deductibles.",
        "expected_behavior": "answer",
        "expected_facts": [
            {"policy": "policy_a", "fact": "Deductible is 100."},
            {"policy": "policy_b", "fact": "Deductible is 200."},
        ],
        "expected_evidence": [
            {"policy": "policy_a", "pages": [1, 3]},
            {"policy": "policy_b", "pages": [2]},
        ],
    }


# =============================================================================
# GROUND-TRUTH VALIDATION
# =============================================================================

def test_valid_ground_truth(example_case):
    """Accept a properly labelled fictional question."""
    assert evaluator.validate_questions([example_case]) == [example_case]


def test_duplicate_case_id_is_rejected(example_case):
    """Duplicate IDs must not silently overwrite evaluation cases."""
    with pytest.raises(ValueError, match="Duplicate case ID"):
        evaluator.validate_questions([example_case, example_case])


def test_invalid_page_is_rejected(example_case):
    """Page zero is not a valid PDF page label."""
    example_case["expected_evidence"][0]["pages"] = [0]

    with pytest.raises(ValueError):
        evaluator.validate_questions([example_case])


def test_mismatched_policy_labels_are_rejected(example_case):
    """Expected facts and evidence must refer to the same policies."""
    example_case["expected_facts"][0]["policy"] = "unknown_policy"

    with pytest.raises(ValueError, match="policies differ"):
        evaluator.validate_questions([example_case])


# =============================================================================
# RETRIEVAL RESULT VALIDATION
# =============================================================================

def test_duplicate_result_id_is_rejected(example_case):
    """A question may have only one ranked retrieval result."""
    results = [
        {"id": example_case["id"], "retrieved": []},
        {"id": example_case["id"], "retrieved": []},
    ]

    with pytest.raises(ValueError, match="Duplicate retrieval result"):
        evaluator.validate_results(results, {example_case["id"]})


def test_unknown_result_id_is_rejected():
    """Unexpected question IDs must not enter the score report."""
    with pytest.raises(ValueError, match="Unknown"):
        evaluator.validate_results(
            [{"id": "unknown", "retrieved": []}],
            {"known"},
        )


# =============================================================================
# RETRIEVAL SCORING
# =============================================================================

def test_perfect_retrieval_scores(example_case):
    """Both policies retrieved at the top should score perfectly."""
    retrieved = [
        {"policy": "policy_a", "page": 1},
        {"policy": "policy_b", "page": 2},
    ]

    result = evaluator.score_case(example_case, retrieved, k=2)

    assert result["hit_at_k"] == 1
    assert result["precision_at_k"] == 1.0
    assert result["recall_at_k"] == 1.0
    assert result["mrr_at_k"] == 1.0


def test_irrelevant_first_result_reduces_rank_quality(example_case):
    """The first relevant result at rank two has reciprocal rank 0.5."""
    retrieved = [
        {"policy": "unrelated", "page": 1},
        {"policy": "policy_a", "page": 3},
    ]

    result = evaluator.score_case(example_case, retrieved, k=2)

    assert result["hit_at_k"] == 1
    assert result["precision_at_k"] == 0.5
    assert result["recall_at_k"] == 0.5
    assert result["mrr_at_k"] == 0.5


def test_empty_retrieval_scores_zero(example_case):
    """No retrieved evidence must produce zero scores."""
    result = evaluator.score_case(example_case, [], k=6)

    assert result["hit_at_k"] == 0
    assert result["precision_at_k"] == 0.0
    assert result["recall_at_k"] == 0.0
    assert result["mrr_at_k"] == 0.0


def test_duplicate_page_does_not_inflate_recall(example_case):
    """Repeated pages cannot satisfy another policy's evidence group."""
    retrieved = [
        {"policy": "policy_a", "page": 1},
        {"policy": "policy_a", "page": 1},
    ]

    result = evaluator.score_case(example_case, retrieved, k=2)

    assert result["matched_policy_groups"] == 1
    assert result["recall_at_k"] == 0.5
    assert result["precision_at_k"] == 0.5


def test_missing_cases_are_reported_not_assumed_failed(example_case):
    """Absent result records are excluded and explicitly identified."""
    report = evaluator.evaluate([example_case], {}, k=6)

    assert report["total_cases"] == 1
    assert report["evaluated_cases"] == 0
    assert report["missing_case_ids"] == ["test_deductible"]
    assert report["macro_average"] == {}


def test_macro_average_uses_evaluated_cases(example_case):
    """One evaluated case must produce its corresponding macro scores."""
    results = {
        example_case["id"]: [
            {"policy": "policy_a", "page": 1},
        ]
    }

    report = evaluator.evaluate([example_case], results, k=6)

    assert report["evaluated_cases"] == 1
    assert report["macro_average"]["hit_at_k"] == 1.0
    assert report["macro_average"]["recall_at_k"] == 0.5