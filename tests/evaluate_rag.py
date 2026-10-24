
"""Compare fixed-size and sentence-aware RAG chunking."""

import json
from pathlib import Path

from langchain_core.documents import Document

from services.rag_service import (
    read_pdf,
    create_langchain_documents,
)
from services.vector_store_service import (
    create_vector_collection,
    add_documents,
    search_similar_documents,
)
from tests.chunking_experiment import create_sentence_chunks


PDF_PATH = "docs/sample_documents/sample_policy_v3_advanced.pdf"
EVALUATION_PATH = "tests/rag_evaluation_cases.json"
TOP_K = 3


def load_evaluation_cases() -> list[dict]:
    """Load questions and expected evidence pages."""

    with open(EVALUATION_PATH, "r", encoding="utf-8") as file:
        return json.load(file)


def prepare_documents(method: str) -> list[Document]:
    """Prepare PDF chunks using the selected method."""

    original_chunks = read_pdf(PDF_PATH)
    source_filename = Path(PDF_PATH).name

    if method == "fixed":
        return create_langchain_documents(
            original_chunks,
            source_filename,
        )

    if method == "sentence":
        # Reconstruct page text without duplicating overlapping chunks.
        # Read the original PDF pages directly for a fair comparison.
        from pypdf import PdfReader

        reader = PdfReader(PDF_PATH)
        documents = []

        for page_number, page in enumerate(reader.pages, start=1):
            page_text = page.extract_text() or ""

            sentence_chunks = create_sentence_chunks(
                page_text,
                max_chunk_size=1000,
                overlap_size=200,
            )

            for chunk_index, text in enumerate(sentence_chunks):
                documents.append(
                    Document(
                        page_content=text,
                        metadata={
                            "source": source_filename,
                            "page": page_number,
                            "chunk_id": chunk_index,
                        },
                    )
                )

        return documents

    raise ValueError(f"Unknown chunking method: {method}")


def evaluate_method(method: str, cases: list[dict]) -> None:
    """Evaluate one chunking strategy."""

    documents = prepare_documents(method)

    collection = create_vector_collection()
    add_documents(collection, documents)

    hit_count = 0
    reciprocal_rank_total = 0.0

    print(f"\n--- {method.upper()} CHUNKING ---")
    print("Total chunks:", len(documents))

    for case in cases:
        results = search_similar_documents(
            collection,
            case["question"],
            top_k=TOP_K,
        )

        retrieved_pages = [
            document.metadata["page"]
            for document in results
        ]

        expected_pages = set(case["expected_pages"])
        first_relevant_rank = None

        for rank, page in enumerate(retrieved_pages, start=1):
            if page in expected_pages:
                first_relevant_rank = rank
                break

        if first_relevant_rank is not None:
            hit_count += 1
            reciprocal_rank_total += 1 / first_relevant_rank

        print("\nQuestion:", case["question"])
        print("Retrieved pages:", retrieved_pages)
        print("First relevant rank:", first_relevant_rank)

    total_questions = len(cases)

    if total_questions == 0:
        raise ValueError("No evaluation cases found.")

    hit_at_3 = hit_count / total_questions
    mrr_at_3 = reciprocal_rank_total / total_questions

    print("\nHit@3:", round(hit_at_3, 3))
    print("MRR@3:", round(mrr_at_3, 3))


def main() -> None:
    """Compare both chunking strategies on the same questions."""

    cases = load_evaluation_cases()

    evaluate_method("fixed", cases)
    evaluate_method("sentence", cases)


if __name__ == "__main__":
    main()
