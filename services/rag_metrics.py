
"""
Module Name: RAG METRICS SERVICE

PURPOSE
-------
Collect request-level performance measurements for the insurance-policy
Retrieval-Augmented Generation (RAG) pipeline.

The measurements help identify bottlenecks in document retrieval,
reranking, context construction, and language-model generation.

ENVIRONMENT / CONFIGURATION
---------------------------
No additional environment variables are required.

A dedicated console logging handler is configured for this module
so that INFO-level RAG metrics are visible in the FastAPI terminal,
even when the application's root logger is configured at WARNING.

DEPENDENCIES
------------
Python standard library:
    - logging
    - contextlib
    - contextvars
    - dataclasses
    - time

Used by:
    - services.document_service

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
1. Collect timing measurements for individual RAG stages.
2. Track retrieved candidates and evidence passage counts.
3. Record the size of the constructed LLM context.
4. Estimate context tokens for baseline analysis.
5. Keep measurements isolated between concurrent requests.
6. Display a performance summary after each RAG request.
7. Preserve existing function interfaces and exception behavior.

SECURITY NOTES
--------------
Performance logs must not include:
    - Authentication tokens or session credentials.
    - Insurance-policy text or retrieved passages.
    - User questions or generated answers.
    - Personally identifiable or medical information.

Only numerical measurements and predefined stage names are logged.

Token counts are approximate estimates, not tokenizer measurements.
"""

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import perf_counter


# ---------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------

logger = logging.getLogger(__name__)

# Allow INFO-level measurements from this module without changing
# logging levels for other services.
logger.setLevel(logging.INFO)

# Configure a dedicated console handler only if one has not already
# been attached to this logger.
#
# This prevents duplicate handlers when the module is imported
# multiple times or during development reloads.
if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # Keep the format readable alongside FastAPI/Uvicorn logs.
    console_formatter = logging.Formatter(
        fmt="%(levelname)s:%(name)s:%(message)s"
    )

    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

# Do not forward these messages to the root logger.
#
# This avoids duplicate output when the application also configures
# root logging handlers.
logger.propagate = False


# ---------------------------------------------------------------------
# Request-level metrics data
# ---------------------------------------------------------------------

@dataclass
class RagMetrics:
    """
    Store performance measurements for one RAG question.

    Timing values are expressed in milliseconds.

    A separate instance is created for each request, ensuring
    measurements are not shared between users or concurrent requests.
    """

    timings_ms: dict[str, float] = field(default_factory=dict)

    candidate_chunks: int = 0
    evidence_chunks: int = 0
    context_characters: int = 0

    def add_time(self, stage: str, elapsed_ms: float) -> None:
        """
        Add elapsed time to a named RAG processing stage.

        Repeated stages are accumulated. This is useful when a
        multi-document question searches several collections.

        Args:
            stage: Name of the measured processing stage.
            elapsed_ms: Elapsed time in milliseconds.

        Raises:
            ValueError: If the supplied elapsed time is negative.
        """
        if elapsed_ms < 0:
            raise ValueError("Elapsed time cannot be negative.")

        previous_time = self.timings_ms.get(stage, 0.0)

        self.timings_ms[stage] = round(
            previous_time + elapsed_ms,
            3,
        )

    def summary(self) -> dict:
        """
        Return a privacy-conscious summary of RAG performance.

        The summary contains numerical measurements only.
        User questions, document contents, and generated responses
        are intentionally excluded.
        """
        return {
            "timings_ms": dict(self.timings_ms),
            "candidate_chunks": self.candidate_chunks,
            "evidence_chunks": self.evidence_chunks,
            "context_characters": self.context_characters,

            # Approximate token count using four characters per token.
            # This is sufficient for an initial performance baseline,
            # but it is not an exact model-specific token count.
            "estimated_context_tokens": (
                self.context_characters + 3
            ) // 4,
        }


# ---------------------------------------------------------------------
# Request-local storage
# ---------------------------------------------------------------------

# ContextVar keeps metrics isolated between concurrent requests.
#
# Unlike a global mutable variable, it prevents one request from
# accidentally adding measurements to another request's results.
_active_metrics: ContextVar[RagMetrics | None] = ContextVar(
    "active_rag_metrics",
    default=None,
)


def current_metrics() -> RagMetrics | None:
    """
    Return the active RAG metrics object for the current request.

    Returns None when execution is outside a measured RAG request.
    """
    return _active_metrics.get()


# ---------------------------------------------------------------------
# Individual stage timing
# ---------------------------------------------------------------------

@contextmanager
def measure_stage(stage: str):
    """
    Measure the execution time of one RAG processing stage.

    This context manager preserves the wrapped operation's return
    value and exception behavior.

    Example:
        with measure_stage("vector_search"):
            results = collection.query(...)

    Timing is recorded even if the wrapped operation raises an
    exception, provided an active request metrics object exists.
    """
    start = perf_counter()

    try:
        yield

    finally:
        metrics = current_metrics()

        if metrics is not None:
            elapsed_ms = (perf_counter() - start) * 1000

            metrics.add_time(
                stage,
                elapsed_ms,
            )


# ---------------------------------------------------------------------
# Complete RAG request measurement
# ---------------------------------------------------------------------

@contextmanager
def record_rag_request():
    """
    Create and manage performance measurements for one RAG request.

    Responsibilities:
        1. Create a fresh RagMetrics instance.
        2. Make it available to the current execution context.
        3. Measure total service execution time.
        4. Log the numerical performance summary.
        5. Restore the previous execution context.

    The summary is emitted even when processing raises an exception.
    This allows failed requests to be investigated using their
    recorded timings without exposing sensitive document data.
    """
    metrics = RagMetrics()

    # Save the context token so the previous state can be restored.
    token = _active_metrics.set(metrics)

    start = perf_counter()

    try:
        yield metrics

    finally:
        try:
            elapsed_ms = (perf_counter() - start) * 1000

            metrics.add_time(
                "service_total",
                elapsed_ms,
            )

            # Log only numeric performance data.
            # Do not add question text, policy excerpts, or tokens.
            logger.info(
                "RAG baseline metrics: %s",
                metrics.summary(),
            )

        finally:
            # Always restore the previous context, including when
            # a logging operation unexpectedly fails.
            _active_metrics.reset(token)