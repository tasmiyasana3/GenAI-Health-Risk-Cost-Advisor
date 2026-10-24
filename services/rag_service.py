
"""
Insurance-policy PDF question answering using MiniLM, ChromaDB,
cross-encoder reranking and Gemini.

V3 RETRIEVAL ENGINEERING DECISIONS
----------------------------------

Version 1:
    TF-IDF retrieval with fixed-size text chunking.

Version 2:
    MiniLM semantic embeddings with ChromaDB.
    Compared fixed-size and sentence-aware chunking.
    Sentence-aware chunking performed better in our initial evaluation.

Version 3:
    Evaluated MiniLM, BM25 and weighted hybrid retrieval.
    Semantic-only retrieval remained the leading candidate.

Current V3:
    MiniLM retrieval + cross-encoder reranking.

WHY WE SELECTED THIS APPROACH
-----------------------------

On our current 11-chunk fictional insurance-policy benchmark
containing six evaluation questions:

    MiniLM only:
        Hit@3 = 0.667
        MRR@3 = 0.583

    MiniLM + cross-encoder reranking:
        Hit@3 = 1.000
        MRR@3 = 0.917

The reranker recovered relevant evidence missed by MiniLM
and improved the ordering of retrieved passages.

IMPORTANT LIMITATIONS
---------------------

These results are based on one fictional policy and six questions.
They do not establish general performance on unseen documents.

This implementation is a V3 prototype:
- PDF indexing happens for every question.
- ChromaDB collections are temporary.
- Authentication and persistent document ownership are not implemented.
- Retrieved evidence is not yet independently verified against
  Gemini's generated answer.

Future work:
- Automated pytest coverage
- Persistent document indexing
- Document-session isolation
- FastAPI endpoints
- Larger retrieval and answer-quality evaluations
"""

import logging
import re
from functools import lru_cache
from pathlib import Path

from pypdf import PdfReader
from sentence_transformers import CrossEncoder

from langchain_core.prompts import PromptTemplate
from langchain_core.documents import Document

from config import get_llm

from services.vector_store_service import (
    create_vector_collection,
    add_documents,
    search_similar_documents,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

MAX_PDF_PAGES = 100

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200

# Retrieve more passages than we ultimately give Gemini.
CANDIDATE_K = 6

# Pass the three highest-ranked passages to Gemini.
TOP_K_RESULTS = 3

RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


# ---------------------------------------------------------
# Gemini prompt
# ---------------------------------------------------------

RAG_PROMPT = PromptTemplate.from_template(
    """
    Answer the question using only the PDF excerpts below.

    If the answer is not present, say that the document
    does not provide enough information.

    Do not invent policy terms or coverage decisions.

    Cite page numbers in your answer.

    Excerpts:
    {context}

    Question: {question}
    """
)


# ---------------------------------------------------------
# Load reranker once
# ---------------------------------------------------------

@lru_cache(maxsize=1)
def get_reranker() -> CrossEncoder:
    """
    Load the cross-encoder model once and reuse it.

    Loading the model for every question would waste
    memory and CPU time.
    """

    logger.info("Loading cross-encoder reranker")

    return CrossEncoder(
        RERANKER_MODEL,
        device="cpu",
    )


# ---------------------------------------------------------
# Sentence-aware chunking
# ---------------------------------------------------------

def split_text_into_chunks(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """
    Split PDF text into sentence-aware overlapping chunks.

    Complete sentences are preferred over arbitrary
    character boundaries.
    """

    if chunk_size <= 0:
        raise ValueError(
            "Chunk size must be greater than zero."
        )

    if overlap < 0 or overlap >= chunk_size:
        raise ValueError(
            "Overlap must be non-negative and smaller than chunk size."
        )

    if not text.strip():
        return []

    sentences = re.split(
        r"(?<=[.!?])\s+",
        text.strip(),
    )

    chunks = []
    current_sentences = []
    current_length = 0

    for sentence in sentences:

        sentence = sentence.strip()

        if not sentence:
            continue

        sentence_length = len(sentence)

        if (
            current_sentences
            and current_length + sentence_length + 1 > chunk_size
        ):

            chunks.append(
                " ".join(current_sentences)
            )

            # Preserve complete sentences for overlap.
            overlap_sentences = []
            overlap_length = 0

            for previous_sentence in reversed(
                current_sentences
            ):

                if overlap_length >= overlap:
                    break

                overlap_sentences.insert(
                    0,
                    previous_sentence,
                )

                overlap_length += (
                    len(previous_sentence) + 1
                )

            current_sentences = overlap_sentences

            current_length = len(
                " ".join(current_sentences)
            )

            # Avoid retaining excessive overlap.
            while (
                current_sentences
                and current_length + sentence_length + 1 > chunk_size
            ):

                current_sentences.pop(0)

                current_length = len(
                    " ".join(current_sentences)
                )

        current_sentences.append(sentence)

        current_length = len(
            " ".join(current_sentences)
        )

    if current_sentences:

        final_chunk = " ".join(
            current_sentences
        )

        if not chunks or final_chunk != chunks[-1]:
            chunks.append(final_chunk)

    return chunks


# ---------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------

def read_pdf(pdf_path: str) -> list[dict]:
    """
    Extract PDF text and split each page into chunks.

    Page numbers are preserved for source citations.
    """

    if not pdf_path:
        raise ValueError(
            "Upload a PDF before asking a question."
        )

    pdf_file = Path(pdf_path)

    if pdf_file.suffix.lower() != ".pdf":
        raise ValueError(
            "Only PDF files are supported."
        )

    if not pdf_file.is_file():
        raise ValueError(
            "The uploaded PDF file could not be found."
        )

    pdf_reader = PdfReader(
        str(pdf_file)
    )

    page_count = len(
        pdf_reader.pages
    )

    if page_count > MAX_PDF_PAGES:
        raise ValueError(
            f"PDF exceeds the maximum limit "
            f"of {MAX_PDF_PAGES} pages."
        )

    document_chunks = []

    for page_number, page in enumerate(
        pdf_reader.pages,
        start=1,
    ):

        extracted_text = (
            page.extract_text() or ""
        )

        page_text = " ".join(
            extracted_text.split()
        )

        if not page_text:
            continue

        page_chunks = split_text_into_chunks(
            page_text
        )

        for chunk_text in page_chunks:

            document_chunks.append(
                {
                    "page": page_number,
                    "text": chunk_text,
                }
            )

    if not document_chunks:
        raise ValueError(
            "No readable text found in the PDF. "
            "Scanned PDFs require OCR, "
            "which is not supported yet."
        )

    logger.info(
        "PDF processed: pages=%d, chunks=%d",
        page_count,
        len(document_chunks),
    )

    return document_chunks


# ---------------------------------------------------------
# LangChain document conversion
# ---------------------------------------------------------

def create_langchain_documents(
    chunks: list[dict],
    source_filename: str,
) -> list[Document]:
    """
    Convert extracted chunks into LangChain Documents.

    Metadata is retained for citation and traceability.
    """

    documents = []

    for chunk_index, chunk in enumerate(chunks):

        document = Document(
            page_content=chunk["text"],
            metadata={
                "source": source_filename,
                "page": chunk["page"],
                "chunk_id": chunk_index,
            },
        )

        documents.append(document)

    return documents


# ---------------------------------------------------------
# Cross-encoder reranking
# ---------------------------------------------------------

def rerank_documents(
    question: str,
    documents: list[Document],
    top_k: int = TOP_K_RESULTS,
) -> list[Document]:
    """
    Rerank candidate passages using a cross-encoder.

    Unlike embedding similarity, a cross-encoder
    evaluates the question and passage together.
    """

    if not documents:
        return []

    if top_k < 1:
        raise ValueError(
            "top_k must be at least 1."
        )

    reranker = get_reranker()

    # Pair the question with each candidate passage.
    question_passage_pairs = [
        (
            question,
            document.page_content,
        )
        for document in documents
    ]

    # Score the relevance of each pair.
    scores = reranker.predict(
        question_passage_pairs
    )

    # Sort documents by descending relevance score.
    ranked_documents = sorted(
        zip(scores, documents),
        key=lambda item: float(item[0]),
        reverse=True,
    )

    return [
        document
        for score, document in ranked_documents[:top_k]
    ]


# ---------------------------------------------------------
# Semantic retrieval + reranking
# ---------------------------------------------------------

def retrieve_relevant_chunks(
    chunks: list[dict],
    question: str,
    top_k: int = TOP_K_RESULTS,
) -> list[dict]:
    """
    Retrieve passages using MiniLM and ChromaDB,
    then rerank them with a cross-encoder.

    Pipeline:
        1. Convert chunks into LangChain Documents.
        2. Generate embeddings and store them in ChromaDB.
        3. Retrieve up to six semantic candidates.
        4. Rerank candidates.
        5. Return the highest-ranked passages.
    """

    if not question or not question.strip():
        raise ValueError(
            "Enter a question about the document."
        )

    if not chunks:
        return []

    if top_k < 1:
        raise ValueError(
            "top_k must be at least 1."
        )

    documents = create_langchain_documents(
        chunks,
        source_filename="uploaded_document.pdf",
    )

    # Temporary collection for this retrieval request.
    collection = create_vector_collection()

    add_documents(
        collection,
        documents,
    )

    # Retrieve a wider candidate set.
    candidate_documents = search_similar_documents(
        collection,
        question,
        top_k=max(CANDIDATE_K, top_k),
    )

    # Rerank candidates by question-passage relevance.
    reranked_documents = rerank_documents(
        question,
        candidate_documents,
        top_k=top_k,
    )

    relevant_chunks = []

    for document in reranked_documents:

        relevant_chunks.append(
            {
                "page": document.metadata["page"],
                "text": document.page_content,
            }
        )

    logger.info(
        "Retrieval completed: candidates=%d, returned=%d",
        len(candidate_documents),
        len(relevant_chunks),
    )

    return relevant_chunks


# ---------------------------------------------------------
# Build Gemini context
# ---------------------------------------------------------

def build_rag_context(
    relevant_chunks: list[dict],
) -> str:
    """
    Format retrieved passages with page citations.
    """

    context_parts = []

    for chunk in relevant_chunks:

        page_number = chunk["page"]
        chunk_text = chunk["text"]

        context_parts.append(
            f"[Page {page_number}]\n{chunk_text}"
        )

    return "\n\n".join(
        context_parts
    )


# ---------------------------------------------------------
# End-to-end RAG
# ---------------------------------------------------------

def answer_document_question(
    pdf_path: str,
    question: str,
) -> str:
    """
    Answer an insurance-policy question using:

        PDF
         -> Sentence-aware chunking
         -> MiniLM embeddings
         -> ChromaDB retrieval
         -> Cross-encoder reranking
         -> Gemini answer with page citations
    """

    if not question or not question.strip():
        raise ValueError(
            "Enter a question about the document."
        )

    # Step 1: Extract and chunk PDF.
    document_chunks = read_pdf(
        pdf_path
    )

    # Step 2: Retrieve and rerank passages.
    relevant_chunks = retrieve_relevant_chunks(
        chunks=document_chunks,
        question=question,
    )

    if not relevant_chunks:
        return (
            "I could not find relevant text "
            "in the uploaded document."
        )

    # Step 3: Build evidence context.
    context = build_rag_context(
        relevant_chunks
    )

    # Step 4: Ask Gemini using retrieved evidence only.
    rag_chain = (
        RAG_PROMPT | get_llm()
    )

    response = rag_chain.invoke(
        {
            "context": context,
            "question": question,
        }
    )

    # Step 5: Extract readable answer.
    response_content = response.content

    if isinstance(response_content, str):
        return response_content

    if isinstance(response_content, list):

        text_parts = []

        for part in response_content:

            if (
                isinstance(part, dict)
                and part.get("type") == "text"
            ):
                text_parts.append(
                    part["text"]
                )

        return "\n".join(
            text_parts
        )

    return str(response_content)
