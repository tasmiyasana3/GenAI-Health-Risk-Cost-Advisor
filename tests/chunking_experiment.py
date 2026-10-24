
"""Experiment with sentence-aware PDF chunking."""

import re


def split_into_sentences(text: str) -> list[str]:
    """Split text at sentence-ending punctuation."""

    sentences = re.split(r"(?<=[.!?])\s+", text)

    return [
        sentence.strip()
        for sentence in sentences
        if sentence.strip()
    ]


def create_sentence_chunks(
    text: str,
    max_chunk_size: int = 1000,
    overlap_size: int = 200,
) -> list[str]:
    """
    Group sentences into chunks with sentence-level overlap.

    The overlap helps preserve context between neighboring chunks.
    """

    if max_chunk_size <= 0:
        raise ValueError("max_chunk_size must be positive.")

    if overlap_size < 0 or overlap_size >= max_chunk_size:
        raise ValueError(
            "overlap_size must be between 0 and max_chunk_size."
        )

    sentences = split_into_sentences(text)

    chunks = []
    current_sentences = []

    for sentence in sentences:

        # A long sentence cannot fit inside the chosen chunk size.
        # Keep it intact for this experiment.
        if len(sentence) > max_chunk_size:
            if current_sentences:
                chunks.append(" ".join(current_sentences))
                current_sentences = []

            chunks.append(sentence)
            continue

        proposed_sentences = current_sentences + [sentence]
        proposed_text = " ".join(proposed_sentences)

        if len(proposed_text) <= max_chunk_size:
            current_sentences.append(sentence)
            continue

        # The current chunk is full, so save it.
        chunks.append(" ".join(current_sentences))

        # Carry complete sentences into the next chunk.
        overlap_sentences = []
        overlap_length = 0

        for previous_sentence in reversed(current_sentences):
            additional_length = len(previous_sentence)

            if overlap_sentences:
                additional_length += 1

            if overlap_length + additional_length > overlap_size:
                break

            overlap_sentences.insert(0, previous_sentence)
            overlap_length += additional_length

        # Start the next chunk with overlap and the new sentence.
        current_sentences = overlap_sentences + [sentence]

        # Prevent overlap from making the next chunk too large.
        while len(" ".join(current_sentences)) > max_chunk_size:
            current_sentences.pop(0)

    if current_sentences:
        chunks.append(" ".join(current_sentences))

    return chunks
