
"""
MODULE NAME
-----------
RAG BASELINE BENCHMARK

PURPOSE
-------
Measure authenticated FastAPI /documents/ask HTTP latency using existing
synthetic documents. The server logs internal RAG stage timings separately.

ENVIRONMENT / CONFIGURATION
---------------------------
Set RAG_BENCHMARK_TOKEN to a valid access JWT and RAG_BENCHMARK_DOCUMENT_IDS
to one or more comma-separated document IDs owned by that login session.

Optional:
    RAG_BENCHMARK_URL
    RAG_BENCHMARK_QUESTIONS
    RAG_BENCHMARK_OUTPUT

SECURITY NOTES
--------------
Never print JWTs or policy text.
No upload, delete, refresh or logout occurs.
Repeated questions invoke Gemini and may incur API charges.
"""

import json
import os
import statistics
import sys
from pathlib import Path
from time import perf_counter

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_QUESTIONS = (
    PROJECT_ROOT
    / "tests"
    / "evaluation"
    / "phase447_questions.json"
)


def main() -> int:
    """Execute one warm-up and three timed requests per question."""

    token = os.getenv("RAG_BENCHMARK_TOKEN", "").strip()

    document_ids = [
        item.strip()
        for item in os.getenv(
            "RAG_BENCHMARK_DOCUMENT_IDS", ""
        ).split(",")
        if item.strip()
    ]

    base_url = os.getenv(
        "RAG_BENCHMARK_URL",
        "http://127.0.0.1:8000",
    ).rstrip("/")

    if not token or not document_ids:
        print(
            "Set RAG_BENCHMARK_TOKEN and "
            "RAG_BENCHMARK_DOCUMENT_IDS first."
        )
        return 2

    questions_path = Path(
        os.getenv(
            "RAG_BENCHMARK_QUESTIONS",
            str(DEFAULT_QUESTIONS),
        )
    )

    cases = json.loads(
        questions_path.read_text(encoding="utf-8")
    )

    if not isinstance(cases, list) or not cases:
        print("Question file must contain a nonempty JSON list.")
        return 2

    results = []

    with httpx.Client(
        timeout=120.0,
        headers={
            "Authorization": f"Bearer {token}",
        },
    ) as client:

        for case in cases:
            question = case["question"]
            times_ms = []

            for attempt in range(4):
                start = perf_counter()

                try:
                    response = client.post(
                        f"{base_url}/documents/ask",
                        json={
                            "question": question,
                            "document_ids": document_ids,
                        },
                    )

                except httpx.HTTPError as error:
                    print(
                        f"{case['id']}: request failed "
                        f"({type(error).__name__})."
                    )
                    return 1

                elapsed_ms = (
                    perf_counter() - start
                ) * 1000

                if response.status_code != 200:
                    print(
                        f"{case['id']}: HTTP "
                        f"{response.status_code}; "
                        "benchmark stopped."
                    )
                    return 1

                if attempt > 0:
                    times_ms.append(
                        round(elapsed_ms, 2)
                    )

            results.append(
                {
                    "id": case["id"],
                    "http_ms": times_ms,
                    "median_http_ms": round(
                        statistics.median(times_ms),
                        2,
                    ),
                }
            )

            print(
                f"{case['id']}: median HTTP "
                f"{results[-1]['median_http_ms']} ms"
            )

    output = Path(
        os.getenv(
            "RAG_BENCHMARK_OUTPUT",
            "phase447_baseline_results.json",
        )
    )

    output.write_text(
        json.dumps(results, indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        f"Results written to {output} "
        "(no credentials or policy text)."
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
