# Phase 4.4.7 — Completion and Engineering Issue Log

## Scope
Phase 4.4.7B: frozen retrieval baseline.
Phase 4.4.7C: deterministic query planning, bounded
multi-topic retrieval, and retrieval evaluation.

## Quality results

| Metric | Phase B K=6 | Phase C K=6 |
|---|---:|---:|
| Hit rate | 0.9000 | 1.0000 |
| Precision | 0.3167 | 0.3833 |
| Recall | 0.7500 | 1.0000 |
| MRR | 0.7333 | 1.0000 |

At K=16:
- Precision: 0.1898 -> 0.3708
- Recall: 1.0000 -> 1.0000
- MRR: 0.7458 -> 1.0000

These metrics use ten fictional-policy evaluation
questions and page-level relevance judgments.

## Retrieval performance

Local retrieval-only benchmark: 10 requests.

- Median: 248.49 ms
- P95: 2489.65 ms
- First request: 4217.30 ms
- Median excluding first request: 247.89 ms
- Policy-summary request: 378.07 ms
- Selected evidence: 6 references per question,
  except policy summary with 8

First-request model loading likely contributed to
the high P95. No equivalent Phase B latency
measurement is available.

## Regression verification

- 266 tests passed
- 35 tests skipped
- 12 subtests passed
- Git whitespace checks passed

Skipped tests are not counted as executed tests.

## Engineering issue log

1. Earlier benchmark command failure
   - Cause included an incompatible implicit
     python-dotenv path-discovery call.
   - Corrected using an explicit .env path.
   - Status: resolved.

2. Benchmark terminal environment
   - Exported JWT was lost after terminal termination.
   - A fresh authorized token was configured.
   - Status: resolved for the successful benchmark.

3. Cold-start latency
   - First retrieval took 4217.30 ms.
   - Subsequent requests were substantially faster.
   - Status: measured; monitor in future performance work.

4. macOS Torch warning
   - Distributed redirect support notice.
   - Status: non-blocking.

5. Hugging Face Hub warning
   - Unauthenticated request notice.
   - Status: non-blocking; no token required for
     the successful local benchmark.

6. Evaluation limitations
   - Page-level matches do not establish passage relevance.
   - Answer faithfulness and citation accuracy were not scored.
   - Only ten fictional-policy questions were evaluated.
   - Status: documented.

7. Database test coverage
   - Thirty-five tests were skipped.
   - Status: retain as a verification limitation
     until their prerequisites are satisfied.

8. Performance comparison
   - Phase C retrieval-only latency was captured.
   - Phase B matching latency was not captured.
   - Status: no comparative speedup claim.

## Final decision

Freeze Phase 4.4.7C retrieval implementation.
Quality evaluation, local retrieval benchmark,
and the executed regression suite have passed.

Do not claim production readiness or end-to-end
answer correctness from these results alone.
