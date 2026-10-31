
"""Unit tests for Phase 4.4.7 baseline measurements."""

import logging
import time

import pytest

from services.rag_metrics import (
    RagMetrics,
    current_metrics,
    measure_stage,
    record_rag_request,
)


def test_metrics_start_empty():
    metrics = RagMetrics()

    assert metrics.summary()["candidate_chunks"] == 0
    assert metrics.summary()["estimated_context_tokens"] == 0


def test_stage_timings_accumulate():
    metrics = RagMetrics()

    metrics.add_time("vector_search", 2.5)
    metrics.add_time("vector_search", 1.25)

    assert metrics.summary()["timings_ms"]["vector_search"] == 3.75


def test_negative_time_is_rejected():
    with pytest.raises(ValueError):
        RagMetrics().add_time("reranking", -1)


def test_request_context_resets_and_logs_no_policy_text(caplog):
    assert current_metrics() is None

    with caplog.at_level(
        logging.INFO,
        logger="services.rag_metrics",
    ):
        with record_rag_request() as metrics:
            assert current_metrics() is metrics

            with measure_stage("vector_search"):
                time.sleep(0.001)

            metrics.candidate_chunks = 6
            metrics.evidence_chunks = 3
            metrics.context_characters = 101

    assert current_metrics() is None
    assert metrics.summary()["estimated_context_tokens"] == 26
    assert metrics.summary()["timings_ms"]["vector_search"] >= 0
    assert metrics.summary()["timings_ms"]["service_total"] >= 0
    assert "candidate_chunks" in caplog.text
    assert "secret policy excerpt" not in caplog.text


def test_context_is_reset_on_exception():
    with pytest.raises(RuntimeError):
        with record_rag_request():
            raise RuntimeError("intentional test error")

    assert current_metrics() is None
