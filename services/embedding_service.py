
"""Generate semantic text embeddings using a local model."""

import logging
from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer


logger = logging.getLogger(__name__)

# Lightweight embedding model suitable for local development.
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


@lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    """
    Load the embedding model once and reuse it.

    Returns:
        The loaded SentenceTransformer model.
    """

    logger.info("Loading embedding model: %s", EMBEDDING_MODEL_NAME)

    model = SentenceTransformer(
        EMBEDDING_MODEL_NAME,
        device="cpu",
    )

    return model


def generate_embeddings(texts: list[str]) -> np.ndarray:
    """
    Convert a list of text passages into numerical vectors.

    Args:
        texts: Text passages to convert into embeddings.

    Returns:
        A NumPy array containing one embedding per passage.

    Raises:
        ValueError: If the input list is empty or contains blank text.
    """

    if not texts:
        raise ValueError("Provide at least one text passage.")

    for text in texts:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("All passages must contain non-empty text.")

    # Reuse the cached model rather than loading it for every request.
    model = get_embedding_model()

    # Normalize vectors so cosine similarity can be calculated efficiently.
    embeddings = model.encode(
        texts,
        batch_size=16,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    logger.info(
        "Generated embeddings: count=%d, dimensions=%d",
        embeddings.shape[0],
        embeddings.shape[1],
    )

    return embeddings
