
"""
MODULE NAME
-----------
PHASE 4.4.7B - AUTHORIZED RETRIEVAL CAPTURE

PURPOSE
-------
Capture real evidence selected by the existing multi-document RAG
retrieval pipeline for fictional insurance policy evaluation.

ENVIRONMENT / CONFIGURATION
---------------------------
Run from the repository root with python -m scripts.capture_phase447_retrieval.

Requires RAG_BENCHMARK_TOKEN and RAG_BENCHMARK_DOCUMENT_IDS.
Requires an isolated PostgreSQL database and isolated Chroma storage.
Requires a JSON policy map containing two actual document UUIDs.

DEPENDENCIES
------------
Python standard library, existing authentication services,
services.document_service, and local retrieval dependencies.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
Validate inputs, authenticate an active session, retrieve evidence
through existing lifecycle controls, preserve evidence order, and
write page-level references for offline evaluation.

SECURITY NOTES
--------------
Use only fictional documents in an isolated test environment.
Never export credentials, document UUIDs, policy passages, or PII.
No Gemini generation is performed.
"""

import argparse
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_QUESTIONS = (
    PROJECT_ROOT / "tests/evaluation/phase447_questions.json"
)

DEFAULT_OUTPUT = (
    PROJECT_ROOT / "tests/evaluation/phase447_retrieval_results.json"
)

ALLOWED_POLICIES = frozenset({
    "samplecare_v3",
    "horizonshield_silver",
})

BROAD_PATTERN = re.compile(
    r"\b(compare|comparison|differences|list all|all exclusions|"
    r"all benefits|summari[sz]e|overview)\b",
    re.IGNORECASE,
)


def read_json(path: Path) -> Any:
    """Read JSON without exposing its contents in error messages."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Unable to read valid JSON input.") from exc


def validate_uuid(value: str) -> str:
    """Validate and normalize a document UUID."""
    try:
        return uuid.UUID(str(value)).hex
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("Invalid document UUID in configuration.") from exc


def load_policy_map(path: Path) -> dict[str, str]:
    """Validate the two-document fictional policy mapping."""
    raw = read_json(path)

    if not isinstance(raw, dict) or len(raw) != 2:
        raise ValueError("Policy map must contain exactly two entries.")

    mapping = {}

    for document_id, policy in raw.items():
        normalized = validate_uuid(document_id)

        if normalized in mapping:
            raise ValueError("Duplicate normalized document UUID.")

        if not isinstance(policy, str):
            raise ValueError("Invalid policy label.")

        mapping[normalized] = policy

    if set(mapping.values()) != ALLOWED_POLICIES:
        raise ValueError("Policy map has incorrect policy labels.")

    return mapping


def validate_questions(data: Any) -> list[dict[str, Any]]:
    """Validate evaluation cases before connecting to services."""
    if not isinstance(data, list) or len(data) != 10:
        raise ValueError("Expected exactly ten evaluation cases.")

    seen = set()

    for case in data:
        if not isinstance(case, dict):
            raise ValueError("Invalid evaluation case.")

        case_id = case.get("id")
        question = case.get("question")
        evidence = case.get("expected_evidence")

        if (
            not isinstance(case_id, str)
            or not case_id.strip()
            or not isinstance(question, str)
            or not question.strip()
            or not isinstance(evidence, list)
        ):
            raise ValueError("Incomplete evaluation case.")

        if case_id in seen:
            raise ValueError("Duplicate evaluation case ID.")

        seen.add(case_id)

        if {
            item.get("policy")
            for item in evidence
            if isinstance(item, dict)
        } != ALLOWED_POLICIES:
            raise ValueError("Evaluation case policy labels mismatch.")

    return data


def verify_configuration(mapping: dict[str, str]) -> str:
    """Validate the explicitly configured document IDs and token."""
    token = os.environ.get("RAG_BENCHMARK_TOKEN", "").strip()

    if not token:
        raise ValueError("Missing benchmark access token.")

    raw_ids = os.environ.get(
        "RAG_BENCHMARK_DOCUMENT_IDS", ""
    ).split(",")

    ids = [value.strip() for value in raw_ids if value.strip()]

    if len(ids) != 2:
        raise ValueError("Expected exactly two configured document IDs.")

    normalized = {validate_uuid(value) for value in ids}

    if normalized != set(mapping):
        raise ValueError("Document IDs do not match the policy map.")

    return token


def capture_evidence(
    questions: list[dict[str, Any]],
    mapping: dict[str, str],
    token: str,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """
    Retrieve selected evidence using existing authorization controls.

    Imports are delayed until configuration validation is complete.
    No answer-generation function or Gemini client is invoked.
    """
    from services.document_service import (
        retrieve_multi_document_chunks,
    )
    from services.session_database_service import (
        is_session_active,
    )
    from services.token_service import verify_access_token

    claims = verify_access_token(token)

    user_id = claims["user_id"]
    session_id = claims["session_id"]

    if not is_session_active(
        session_id=session_id,
        user_id=user_id,
    ):
        raise ValueError("Benchmark login session is inactive.")

    records = []
    retrieval_modes = {}

    for case in questions:
        question = case["question"]

        documents, _ = retrieve_multi_document_chunks(
            question=question,
            document_ids=list(mapping),
            user_id=user_id,
            session_id=session_id,
        )

        references = []

        for document in documents:
            metadata = document.metadata
            document_id = validate_uuid(
                metadata.get("document_id")
            )
            page = metadata.get("page")

            if document_id not in mapping:
                raise ValueError(
                    "Retrieved evidence does not belong to selected PDFs."
                )

            if type(page) is not int or page < 1:
                raise ValueError(
                    "Retrieved evidence has invalid page metadata."
                )

            references.append({
                "policy": mapping[document_id],
                "page": page,
            })

        records.append({
            "id": case["id"],
            "retrieved": references,
        })

        retrieval_modes[case["id"]] = (
            "broad_query_eligible"
            if BROAD_PATTERN.search(question)
            else "semantic"
        )

        print(
            f"{case['id']}: "
            f"{len(references)} selected evidence references"
        )

    return records, retrieval_modes


def main() -> int:
    """Validate, capture, and save real retrieval evidence."""
    parser = argparse.ArgumentParser(
        description="Capture Phase 4.4.7B RAG evidence."
    )

    parser.add_argument(
        "--policy-map",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--questions",
        type=Path,
        default=DEFAULT_QUESTIONS,
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )

    args = parser.parse_args()

    try:
        if args.output.exists():
            raise ValueError("Output already exists; refusing overwrite.")

        if args.output.resolve() == args.questions.resolve():
            raise ValueError("Output cannot replace ground truth.")

        mapping = load_policy_map(args.policy_map)
        questions = validate_questions(read_json(args.questions))
        token = verify_configuration(mapping)

        records, modes = capture_evidence(
            questions, mapping, token
        )

        args.output.parent.mkdir(parents=True, exist_ok=True)

        with args.output.open("x", encoding="utf-8") as file:
            json.dump(records, file, indent=2)
            file.write("\n")

        print(f"PASS: captured {len(records)} evaluation cases.")
        print("Retrieval mode classification:")
        for case_id, mode in modes.items():
            print(f"  {case_id}: {mode}")

        print(
            "NOTE: broad_query_eligible indicates the question "
            "matches the broad-query pattern; the service may "
            "fall back to semantic retrieval if the context is too large."
        )

        return 0

    except (ValueError, KeyError, OSError) as exc:
        parser.exit(
            1,
            f"Capture failed: {type(exc).__name__}. "
            "Check isolated environment, document ownership, "
            "session validity and metadata.\n",
        )


if __name__ == "__main__":
    raise SystemExit(main())