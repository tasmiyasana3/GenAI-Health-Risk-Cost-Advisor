
"""Compare semantic retrieval, BM25, and weighted hybrid RRF."""

import json

from pypdf import PdfReader
from rank_bm25 import BM25Okapi

from tests.chunking_experiment import create_sentence_chunks
from services.embedding_service import generate_embeddings


PDF_PATH = "docs/sample_documents/sample_policy_v3_advanced.pdf"
EVALUATION_PATH = "tests/rag_evaluation_cases.json"
TOP_K = 3

# Experimental semantic weights.
WEIGHTS = [0.5, 0.7, 0.8]


def reciprocal_rank_fusion(
    semantic_indices: list[int],
    bm25_indices: list[int],
    semantic_weight: float = 0.5,
    k: int = 60,
) -> list[int]:
    """Combine rankings using weighted Reciprocal Rank Fusion."""

    bm25_weight = 1.0 - semantic_weight
    scores = {}

    # Semantic contribution.
    for rank, chunk_id in enumerate(semantic_indices, start=1):
        scores[chunk_id] = (
            scores.get(chunk_id, 0)
            + semantic_weight / (k + rank)
        )

    # BM25 contribution.
    for rank, chunk_id in enumerate(bm25_indices, start=1):
        scores[chunk_id] = (
            scores.get(chunk_id, 0)
            + bm25_weight / (k + rank)
        )

    return sorted(
        scores,
        key=lambda chunk_id: scores[chunk_id],
        reverse=True,
    )


def find_relevant_rank(
    ranked_indices: list[int],
    pages: list[int],
    expected_pages: set[int],
) -> int | None:
    """Find the first relevant result within the top K."""

    for rank, chunk_id in enumerate(ranked_indices[:TOP_K], start=1):
        if pages[chunk_id] in expected_pages:
            return rank

    return None


def main():
    # 1. Read the PDF and create sentence-aware chunks.
    reader = PdfReader(PDF_PATH)

    chunks = []
    pages = []

    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""

        page_chunks = create_sentence_chunks(
            text,
            max_chunk_size=1000,
            overlap_size=200,
        )

        for chunk in page_chunks:
            chunks.append(chunk)
            pages.append(page_number)

    # 2. Generate chunk embeddings only once.
    chunk_embeddings = generate_embeddings(chunks)

    # 3. Build the BM25 keyword index.
    tokenized_chunks = [
        chunk.lower().split()
        for chunk in chunks
    ]

    bm25 = BM25Okapi(tokenized_chunks)

    # 4. Load evaluation questions.
    with open(EVALUATION_PATH, "r", encoding="utf-8") as file:
        evaluation_cases = json.load(file)

    if not evaluation_cases:
        raise ValueError("No evaluation questions found.")

    # Track evaluation metrics for every method.
    methods = ["Semantic", "BM25"]

    for weight in WEIGHTS:
        methods.append(f"Hybrid {round(weight * 100)}/{round((1 - weight) * 100)}")

    results = {
        method: {"hits": 0, "reciprocal_rank_sum": 0.0}
        for method in methods
    }

    print("Total chunks:", len(chunks))
    print("Questions:", len(evaluation_cases))

    # 5. Evaluate every question.
    for question_number, case in enumerate(evaluation_cases, start=1):
        question = case["question"]
        expected_pages = set(case["expected_pages"])

        # Semantic ranking.
        question_embedding = generate_embeddings([question])[0]
        semantic_scores = chunk_embeddings @ question_embedding

        semantic_indices = sorted(
            range(len(chunks)),
            key=lambda index: semantic_scores[index],
            reverse=True,
        )

        # BM25 ranking.
        bm25_scores = bm25.get_scores(question.lower().split())

        bm25_indices = sorted(
            range(len(chunks)),
            key=lambda index: bm25_scores[index],
            reverse=True,
        )

        # Store all rankings for this question.
        rankings = {
            "Semantic": semantic_indices,
            "BM25": bm25_indices,
        }

        # Generate weighted hybrid rankings.
        for weight in WEIGHTS:
            method_name = (
            f"Hybrid {round(weight * 100)}/{round((1 - weight) * 100)}"
            )

            rankings[method_name] = reciprocal_rank_fusion(
                semantic_indices,
                bm25_indices,
                semantic_weight=weight,
            )

        print(f"\nQuestion {question_number}: {question}")
        print("Expected pages:", sorted(expected_pages))

        # 6. Evaluate each method on this question.
        for method_name, ranked_indices in rankings.items():
            retrieved_pages = [
                pages[index]
                for index in ranked_indices[:TOP_K]
            ]

            relevant_rank = find_relevant_rank(
                ranked_indices,
                pages,
                expected_pages,
            )

            if relevant_rank is not None:
                results[method_name]["hits"] += 1
                results[method_name]["reciprocal_rank_sum"] += (
                    1 / relevant_rank
                )

            print(
                f"{method_name}: "
                f"pages={retrieved_pages}, "
                f"relevant_rank={relevant_rank}"
            )

    # 7. Calculate final metrics.
    total_questions = len(evaluation_cases)

    print("\n--- RETRIEVAL COMPARISON ---")
    print(f"{'Method':<18} {'Hit@3':<10} {'MRR@3':<10}")
    print("-" * 40)

    for method_name, metrics in results.items():
        hit_at_3 = metrics["hits"] / total_questions
        mrr_at_3 = metrics["reciprocal_rank_sum"] / total_questions

        print(
            f"{method_name:<18} "
            f"{hit_at_3:<10.3f} "
            f"{mrr_at_3:<10.3f}"
        )


if __name__ == "__main__":
    main()
