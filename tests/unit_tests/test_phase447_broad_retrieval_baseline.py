
"""
MODULE NAME
-----------
PHASE 4.4.7 - BROAD RETRIEVAL BASELINE REGRESSION TESTS

PURPOSE
-------
Verify that captured comprehensive retrieval contains expected
policy-page evidence for the four broad-query benchmark cases.

ENVIRONMENT / CONFIGURATION
---------------------------
Run from the repository root using Python 3.11 or newer.

DEPENDENCIES
------------
Python standard library only.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Confirm that every broad-query benchmark case is present.
2. Verify full expected-policy page coverage.
3. Detect missing or malformed retrieval references.
4. Preserve the historical baseline independently of live services.

SECURITY NOTES
--------------
Uses fictional policy labels and page references only.
Does not access tokens, private documents, databases, or LLMs.
"""

import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVALUATION_DIR = PROJECT_ROOT / "tests" / "evaluation"

QUESTIONS_PATH = EVALUATION_DIR / "phase447_questions.json"
RESULTS_PATH = EVALUATION_DIR / "phase447_retrieval_results.json"

BROAD_CASE_IDS = (
    "exclusions",
    "copayment",
    "claim_deadlines",
    "policy_summary",
)


def load_json(path: Path) -> list:
    """Load a JSON array and reject unexpected root structures."""
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array: {path.name}")

    return data


class TestBroadRetrievalBaseline(unittest.TestCase):
    """Check historical broad-query retrieval evidence coverage."""

    @classmethod
    def setUpClass(cls):
        """Load the frozen benchmark fixtures once."""
        questions = load_json(QUESTIONS_PATH)
        results = load_json(RESULTS_PATH)

        cls.questions = {
            item["id"]: item for item in questions
        }
        cls.results = {
            item["id"]: item["retrieved"] for item in results
        }

        if len(cls.questions) != len(questions):
            raise ValueError("Duplicate benchmark question IDs.")

        if len(cls.results) != len(results):
            raise ValueError("Duplicate retrieval result IDs.")

    def test_all_broad_cases_are_present(self):
        """Require every expected broad-query case."""
        for case_id in BROAD_CASE_IDS:
            with self.subTest(case_id=case_id):
                self.assertIn(case_id, self.questions)
                self.assertIn(case_id, self.results)

    def test_broad_cases_cover_expected_policy_pages(self):
        """Require at least one expected page from each policy."""
        for case_id in BROAD_CASE_IDS:
            with self.subTest(case_id=case_id):
                expected = {
                    item["policy"]: set(item["pages"])
                    for item in self.questions[case_id][
                        "expected_evidence"
                    ]
                }

                retrieved = self.results[case_id]

                matched = set()

                for reference in retrieved:
                    policy = reference["policy"]
                    page = reference["page"]

                    self.assertIsInstance(policy, str)
                    self.assertIs(type(page), int)
                    self.assertGreaterEqual(page, 1)

                    if (
                        policy in expected
                        and page in expected[policy]
                    ):
                        matched.add(policy)

                self.assertEqual(
                    matched,
                    set(expected),
                    f"{case_id}: expected-policy coverage incomplete",
                )

    def test_broad_cases_have_captured_evidence(self):
        """Reject empty historical retrieval results."""
        for case_id in BROAD_CASE_IDS:
            with self.subTest(case_id=case_id):
                self.assertGreater(
                    len(self.results[case_id]),
                    0,
                )


if __name__ == "__main__":
    unittest.main()