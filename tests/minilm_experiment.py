
"""Evaluate MiniLM semantic retrieval without Gemini."""

import json
from pathlib import Path

import numpy as np

from services.rag_service import (
    read_pdf,
    create_langchain_documents,
)
from services.embedding_service import generate_embeddings


PDF_PATH = Path("docs/sample_documents/sample_policy_v3_advanced.pdf")
EVALUATION_PATH = Path("tests/rag_evaluation_cases.json")
TOP_K = 3


def load_evaluation_cases():
    with open(EVALUATION_PATH, "r", encoding="utf-8") as file:
        return json.load(file)


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

    # Embed document chunks once.
    document_embeddings = generate_embeddings(
        [doc.page_content for doc in documents]
    )

    cases = load_evaluation_cases()
    ranks = []

    print(f"Total chunks: {len(documents)}")

    for case in cases:
        question = case["question"]
        expected_pages = set(case["expected_pages"])

        question_embedding = generate_embeddings([question])[0]

        # Embeddings are normalized by embedding_service.py.
        scores = document_embeddings @ question_embedding

        ranked_indices = np.argsort(scores)[::-1][:TOP_K]

        retrieved_pages = [
            documents[index].metadata["page"]
            for index in ranked_indices
        ]

        rank = next(
            (
                position
                for position, page in enumerate(retrieved_pages, start=1)
                if page in expected_pages
            ),
            None,
        )

        ranks.append(rank)

        print(f"\nQuestion: {question}")
        print(f"Retrieved pages: {retrieved_pages}")
        print(f"Relevant rank: {rank}")

    hit, mrr = calculate_metrics(ranks)

    print("\n--- MiniLM Evaluation ---")
    print(f"Hit@{TOP_K}: {hit:.3f}")
    print(f"MRR@{TOP_K}: {mrr:.3f}")


if __name__ == "__main__":
    main()
