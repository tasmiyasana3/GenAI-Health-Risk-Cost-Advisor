
"""Compare MiniLM retrieval with cross-encoder reranking."""

import json
from pathlib import Path

import numpy as np
from sentence_transformers import CrossEncoder

from services.rag_service import (
    read_pdf,
    create_langchain_documents,
)
from services.embedding_service import generate_embeddings


PDF_PATH = Path("docs/sample_documents/sample_policy_v3_advanced.pdf")
EVALUATION_PATH = Path("tests/rag_evaluation_cases.json")

TOP_K = 3
CANDIDATE_K = 6
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def load_evaluation_cases():
    with open(EVALUATION_PATH, "r", encoding="utf-8") as file:
        return json.load(file)


def find_relevant_rank(documents, indices, expected_pages):
    """Find the first retrieved chunk from an expected evidence page."""

    expected_pages = set(expected_pages)

    for rank, index in enumerate(indices, start=1):
        if documents[index].metadata["page"] in expected_pages:
            return rank

    return None


def calculate_metrics(ranks):
    total = len(ranks)

    hit_at_k = sum(rank is not None for rank in ranks) / total

    mrr_at_k = sum(
        1 / rank for rank in ranks if rank is not None
    ) / total

    return hit_at_k, mrr_at_k


def main():
    chunks = read_pdf(str(PDF_PATH))
    documents = create_langchain_documents(
        chunks,
        PDF_PATH.name,
    )

    cases = load_evaluation_cases()

    # Generate MiniLM embeddings once for the entire document.
    document_embeddings = generate_embeddings(
        [doc.page_content for doc in documents]
    )

    # Load the reranker once.
    reranker = CrossEncoder(
        RERANKER_MODEL,
        device="cpu",
    )

    semantic_ranks = []
    reranked_ranks = []

    print(f"Total chunks: {len(documents)}")

    for case in cases:
        question = case["question"]
        expected_pages = case["expected_pages"]

        question_embedding = generate_embeddings([question])[0]

        # Step 1: Retrieve the most similar candidate chunks.
        similarity_scores = document_embeddings @ question_embedding

        semantic_indices = np.argsort(similarity_scores)[::-1]

        candidate_indices = semantic_indices[
            :min(CANDIDATE_K, len(documents))
        ]

        # MiniLM-only baseline.
        baseline_indices = semantic_indices[:TOP_K]

        baseline_rank = find_relevant_rank(
            documents,
            baseline_indices,
            expected_pages,
        )

        # Step 2: Prepare question-passage pairs for the reranker.
        pairs = [
            (question, documents[index].page_content)
            for index in candidate_indices
        ]

        # Step 3: Cross-encoder scores every question-passage pair.
        reranker_scores = np.asarray(
            reranker.predict(pairs)
        ).reshape(-1)

        # Step 4: Reorder the candidates by reranker score.
        reranked_positions = np.argsort(reranker_scores)[::-1]

        reranked_indices = [
            candidate_indices[position]
            for position in reranked_positions[:TOP_K]
        ]

        reranked_rank = find_relevant_rank(
            documents,
            reranked_indices,
            expected_pages,
        )

        semantic_ranks.append(baseline_rank)
        reranked_ranks.append(reranked_rank)

        semantic_pages = [
            documents[index].metadata["page"]
            for index in baseline_indices
        ]

        reranked_pages = [
            documents[index].metadata["page"]
            for index in reranked_indices
        ]

        print(f"\nQuestion: {question}")
        print(f"MiniLM pages: {semantic_pages}, rank: {baseline_rank}")
        print(f"Reranked pages: {reranked_pages}, rank: {reranked_rank}")

    semantic_hit, semantic_mrr = calculate_metrics(semantic_ranks)
    reranked_hit, reranked_mrr = calculate_metrics(reranked_ranks)

    print("\n--- Retrieval Comparison ---")
    print(f"{'Method':<22} {'Hit@3':<10} {'MRR@3':<10}")
    print(f"{'MiniLM':<22} {semantic_hit:<10.3f} {semantic_mrr:<10.3f}")
    print(
        f"{'MiniLM + Reranker':<22} "
        f"{reranked_hit:<10.3f} {reranked_mrr:<10.3f}"
    )


if __name__ == "__main__":
    main()
