# GenAI Health Risk & Cost Advisor — V3

**Status:** Local development prototype · **Branch:** `version_3` · **Verified through:** Phase 4.4.6 (29 October 2026)

An insurance analytics and policy-document intelligence project combining an existing scikit-learn insurance-cost prediction workflow with a FastAPI-based, retrieval-augmented generation (RAG) backend. Users can authenticate, upload text-based **insurance policy PDFs**, and ask evidence-grounded questions about one or more policies.

> **Disclaimer:** This is a research/portfolio prototype, not an insurance quotation, underwriting system, clinical diagnostic tool, or authoritative coverage determination. Check the original policy wording before making consequential decisions. Do not upload real customer data to an unreviewed deployment.

## Current capabilities

| Area | Implemented in V3 |
| --- | --- |
| Insurance-cost prediction | Existing trained scikit-learn pipeline for structured-input cost estimation; Gemini can explain the estimate and draft an advisory. The LLM does **not** calculate the numerical prediction. |
| Policy PDF ingestion | PDF text extraction, sentence-aware chunking, MiniLM embeddings, persistent per-document ChromaDB collections and PostgreSQL document registry. |
| Policy Q&A | Semantic retrieval, cross-encoder reranking, evidence/page citations, single- and multi-policy questions, and Gemini answer generation. |
| Authentication | Registration, Argon2id password hashing, JWT access tokens, PostgreSQL-backed sessions, HttpOnly refresh cookie, refresh rotation and logout. |
| Authorization | Authenticated document endpoints enforce user and session ownership, including expiration checks. |
| Temporary document lifecycle | 30-minute inactivity expiration; cleanup on logout; optional scheduled cleanup every 600 seconds; PostgreSQL advisory locks coordinate document operations and deletion. |
| Backward compatibility | Pre-migration ownerless document records are preserved by cleanup but excluded from authenticated document access. |

**Verification:** The latest default regression run reported **184 passed, 29 skipped, 0 failed**. The 29 skips match the prior baseline; their individual reasons were not re-audited in that run. Live tests verified upload, expiration-based access restriction, logout deletion, and the disappearance of an expired disposable document from both PostgreSQL and ChromaDB while scheduled cleanup was enabled. No scheduler execution log was captured, so the live result is consistent with—but does not independently prove the trigger was—the scheduler.

## Architecture

```text
Client / Swagger / future authenticated Gradio UI
                    |
                 FastAPI
             /       |       \
      Authentication |     ML cost prediction / advisory
       and sessions  |              |
             |       |       saved scikit-learn pipeline
        PostgreSQL   |              + Gemini explanation
                     |
          Authenticated policy API
                     |
             Document service
               /          \
      PostgreSQL registry  PDF extraction + chunking
       (owner/session,          |
        expiration)        MiniLM embeddings
               \             /
                Persistent ChromaDB
                       |
              Semantic retrieval
                       |
              Cross-encoder reranking
                       |
              Evidence and citations
                       |
                Gemini policy answer

Session lifecycle: PostgreSQL session state + advisory locks
                   -> logout / scheduled expiry cleanup
                   -> ChromaDB vectors, then SQL metadata
```

**Storage responsibilities:** PostgreSQL stores users, sessions, migration history and policy-document metadata. ChromaDB stores embedded policy passages and their source metadata. The ML prediction pipeline remains independent of policy RAG.

## End-to-end workflows

### 1. Account and session lifecycle

1. A client registers with an email and password; the backend validates inputs and stores an Argon2id password hash, never plaintext credentials.
2. Login verifies the credentials, creates a PostgreSQL-backed session, returns a short-lived JWT access token, and sets an HttpOnly refresh-token cookie.
3. Protected endpoints validate both the access token and the associated active database session. A valid token is not, by itself, permission to access a policy.
4. Refresh rotates the refresh credential through the session database; logout revokes the session and triggers cleanup of its temporary policies.

### 2. Policy ingestion and indexing

```text
Authenticated request + PDF
   -> validate owner/session and PDF
   -> extract page text (pypdf)
   -> sentence-aware overlapping chunks + source/page metadata
   -> MiniLM embeddings
   -> persistent per-document ChromaDB collection
   -> PostgreSQL document registry (owner, session, status, expiry)
   -> ready document ID
```

The persistent index avoids re-embedding the entire PDF for every question. Ingestion failures are handled with cleanup of partially created document state. Duplicate-detection behavior is scoped to the authenticated session in the temporary-document workflow.

### 3. Grounded policy question answering

```text
Authenticated question + permitted document IDs
   -> verify session, ownership, expiry and document readiness
   -> retrieve candidate passages from selected policy collections
   -> cross-encoder reranking / evidence selection
   -> evidence identifiers, document names and page references
   -> Gemini answer constrained to supplied policy excerpts
   -> return answer with traceable evidence
```

The system supports single-policy questions and comparisons across selected policies. The answer should distinguish clauses actually found in the source from information that the policy does not state. Retrieval quality and prompt efficiency remain evaluation targets; they are not claimed as solved merely because example questions passed.

### 4. Temporary policy lifecycle

A policy is bound to an authenticated user **and** a login session. Successful authorized activity can extend the 30-minute inactivity deadline. When the session logs out, the application removes its temporary vectors and registry rows. An optional background scheduler checks for expired temporary documents independently of logout. PostgreSQL advisory locks protect against conflicting document operations; old records without session ownership are excluded from this automatic deletion path.

## Development milestones

| Phase | Delivered | Evidence / notes |
| --- | --- | --- |
| **1** | Semantic policy retrieval: sentence-aware chunks, MiniLM/ChromaDB, cross-encoder reranking and grounded Gemini answers. | Six-question retrieval experiments; eight tests passed at Phase 1 checkpoint. |
| **2** | Persistent document indexing and FastAPI upload/ask endpoints; index once, query repeatedly. | Persistent index and API checks; 21 tests passed at Phase 2 checkpoint. |
| **3** | PostgreSQL registry, multi-document policy comparison, document/page evidence references, duplicate handling and citation validation. | Fictional-policy end-to-end tests; 53 tests passed at Phase 3 checkpoint. |
| **4.1** | Versioned SQL migrations, users and nullable document ownership schema, migration checksums, database backup/restore checks. | Migration and recovery validation completed locally. |
| **4.2** | Registration endpoint, Argon2id password hashing, input validation and isolated PostgreSQL tests. | 18 reusable tests; full-suite checkpoint: 65 passed, 6 skipped. |
| **4.3A–F** | JWT creation/validation, persistent sessions, login, refresh-token rotation/replay handling, logout and authentication regression checks. | Completed before Phase 4.4.6; see phase engineering records for detailed checkpoints. |
| **4.4–4.4.5** | Protected policy endpoints and authenticated document ownership/session access. | Included in the verified Phase 4.4.6 baseline. |
| **4.4.6** | Session-scoped temporary PDF lifecycle, inactivity expiry, logout/scheduled cleanup, operation locks and migration 007. | **184 passed, 29 skipped, 0 failed**, plus live PostgreSQL/ChromaDB checks. |
| **4.4.7** | Retrieval efficiency measurement and optimization (irrelevant chunks, prompt/context size, latency, citation quality). | **Next; not started.** |

### Phase 4.4.6 — Temporary document lifecycle (latest)

1. Authenticated uploads derive `user_id` and `session_id` from verified credentials rather than trusting client-supplied ownership.
2. Each policy receives a document ID, PostgreSQL registry entry, and a persistent ChromaDB collection of extracted chunks.
3. List, read, ask and delete operations are scoped to the owning active session. The inactivity deadline is 30 minutes and can be refreshed by successful document activity.
4. PostgreSQL advisory locks coordinate document use with cleanup, so cleanup can skip busy sessions and recheck eligibility.
5. Logout revokes the session and cleans up its temporary document metadata and vectors.
6. Optional periodic cleanup processes expired documents and expired/revoked sessions; it removes ChromaDB data before SQL metadata and retains metadata for retry if vector deletion fails.
7. Legacy documents with no session ownership are preserved and are not exposed through authenticated document APIs.

**Relevant implementation files:**

```text
api/main.py
services/document_service.py
services/database_service.py
services/document_lifecycle.py
services/document_operation_lock.py
services/logout_session_service.py
database/migrations/007_add_temporary_document_sessions.sql
```

**Relevant test files:**

```text
tests/test_api.py
tests/test_document_service.py
tests/integration_tests/test_phase44_document_lock_db.py
tests/unit_tests/test_phase44_document_lifecycle.py
tests/unit_tests/test_phase44_document_operation_lock.py
tests/unit_tests/test_phase44_document_route_auth.py
```

### Database evolution

The PostgreSQL schema is managed by `database/migrate.py` and SQL files in `database/migrations/`. Earlier migrations establish users, nullable document ownership, migration history/checksums, session persistence and refresh-token history. **Migration 007** adds temporary-document session ownership, activity/expiration timestamps and related constraints/indexes. Existing ownerless policy records remain intact.

Apply migrations using the repository's documented migration workflow and a verified backup. Do not edit already-applied migration files. A manually applied migration should be reconciled with migration-history tracking before moving to a fresh environment.

## API interaction and operational boundaries

The interactive API explorer is available at `/docs` after starting FastAPI. The tested workflows include registration/login, refresh/logout, authenticated policy upload, document listing/access, question answering, and deletion. Exact request schemas and routes should be taken from the running OpenAPI specification, rather than assumed from older project notes.

For local testing, use **fictional insurance policies** and a dedicated test account. A typical manual check is: register/login -> authorize Swagger with the access token -> upload a policy -> ask a policy-specific question -> verify citations -> log out -> confirm its PostgreSQL registry row and ChromaDB collection were removed.

**Deployment note:** The built-in periodic cleanup is designed for the current local single-worker development setup. Multi-worker or distributed deployment needs a reviewed single-leader scheduling strategy, reliable storage, logging, recovery procedures, and separate security review.

## Local development

Prerequisites: Python and the dependencies in `requirements.txt`, PostgreSQL, a supported Gemini API configuration, and the project's model artifacts as required for ML inference. Use a local virtual environment.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Configure the required database, Gemini, JWT and cookie settings in a **local `.env`** (never commit real secrets). For scheduled temporary-document cleanup, use:

```dotenv
ENABLE_DOCUMENT_CLEANUP=true
DOCUMENT_CLEANUP_INTERVAL_SECONDS=600
```

The local scheduler is opt-in, uses a minimum interval of 60 seconds, and is intended for a single API worker in this prototype. Run FastAPI:

```bash
python -m uvicorn api.main:app --reload
```

API documentation: `http://127.0.0.1:8000/docs`
Health endpoint: `http://127.0.0.1:8000/health`

The existing `app.py` Gradio workflow remains separate; a fully authenticated Gradio-to-FastAPI interface is planned for Phase 5.

## Quality and verification strategy

The repository includes API tests, service tests, unit tests for document lifecycle and operation locks, and a PostgreSQL-backed advisory-lock integration test. Regression testing is run after security/lifecycle changes, and live tests independently inspect both the SQL registry and vector collections.

## Testing

```bash
python -m pytest -q
python -m pytest -q -rs  # Show skip reasons
```

Some PostgreSQL integration suites require explicit opt-in and an **isolated test database**. Check the relevant test fixtures and environment requirements before enabling them; never run destructive integration tests against the working `health_rag_db`.

**Phase 4.4.6 live verification (29 October 2026):**

- A fictional policy upload returned a ready document with authenticated ownership and an expiration timestamp.
- A logout request removed its PostgreSQL row and ChromaDB collection (two chunks).
- A separate disposable policy was deliberately marked expired in PostgreSQL; its row and ChromaDB collection were later absent while automatic cleanup was enabled.
- Final default regression: **184 passed, 29 skipped, 0 failed**.

These checks establish local behavior for the tested paths, not comprehensive security, reliability or load validation.

## Development progress and end-to-end roadmap

**Current checkpoint (29 October 2026):** The local V3 backend is verified through **Phase 4.4.6**. Phases **1–3** and the implemented **4.1–4.4.6** milestones have completed their recorded local checks. **Phase 4.4.7 is next and has not started.** Phases **5–8** remain future work. This is a milestone status, **not** a claim that the overall product is production-ready or a percentage-complete estimate.

| Phase | Objective and planned deliverables | Status |
| --- | --- | --- |
| **1 — Semantic RAG foundation** | Extract text from insurance-policy PDFs; sentence-aware chunking; MiniLM embeddings; ChromaDB semantic retrieval; cross-encoder reranking; grounded Gemini answers and initial retrieval experiments. | **Complete — local prototype** |
| **2 — Persistent RAG and FastAPI** | Upload once/query many; persistent per-document ChromaDB indexing; FastAPI endpoints; PDF metadata and page references; service/API tests. | **Complete — local prototype** |
| **3 — Multi-policy document intelligence** | PostgreSQL document registry; select and compare multiple insurance policies; preserve filename/page evidence; duplicate detection and citation validation. | **Complete — local prototype** |
| **4.1 — Database foundations** | PostgreSQL users/document ownership schema, versioned migrations, migration checksums, backups and restore verification. | **Complete — local checks** |
| **4.2 — Account registration** | Registration API, validation, Argon2id password hashing, database integration and reusable tests. | **Complete — verified** |
| **4.3A–F — Authentication and sessions** | JWT issuance/validation; persistent login sessions; HttpOnly refresh cookies; rotation/replay handling; logout/revocation; authentication regression tests. | **Complete — local checks** |
| **4.4–4.4.5 — Protected policy access** | Require authenticated active sessions on document endpoints; restrict upload, listing, retrieval, question answering and deletion to authorized user/session scope. | **Complete — verified in current baseline** |
| **4.4.6 — Temporary policy-document lifecycle** | Session-scoped document ownership; 30-minute inactivity expiry; logout and optional scheduled cleanup of PostgreSQL/ChromaDB; advisory locks; migration 007; unit/integration/API coverage. | **Complete — 184 passed, 29 skipped; live deletion checks passed** |
| **4.4.7 — Retrieval efficiency** | Establish a repeatable baseline for irrelevant/redundant retrieved chunks, context size and estimated token use, retrieval/answer latency, coverage and citation correctness; optimize with measured trade-offs and regression protection. | **Next — not started** |
| **5 — Authenticated user interface** | Integrate Gradio with the authenticated FastAPI backend: register/login/logout, refresh handling, policy upload/list/selection, multi-policy Q&A, citations, expiry-aware UX and error states. | **Planned** |
| **6 — End-to-end reliability and security** | Validate full user journeys and failure recovery; privacy/security review, negative authorization tests, robust error handling, structured logging/observability and operational safeguards. | **Planned** |
| **7 — Systematic RAG evaluation and performance** | Broader synthetic insurance-policy benchmark; retrieval relevance/coverage, citation faithfulness, answer correctness, latency and resource measurements; compare approaches and document limitations. | **Planned** |
| **8 — CI/CD and deployment** | Containerization as appropriate; GitHub Actions test/migration gates; durable database/vector storage; secret management; backup/restore; hosting-cost review; staging and remote smoke tests. | **Planned — deployment decisions not finalized** |

### What is working now versus what is still needed

**Implemented and locally verified:** insurance-cost prediction/advisory as an existing independent workflow; authenticated FastAPI insurance-policy ingestion and question answering; persistent semantic indexes; multi-policy citations; PostgreSQL-backed accounts/sessions; document isolation; inactivity expiry and deletion from both stores. The latest default regression run was **184 passed, 29 skipped, 0 failed**. The skipped cases were not individually audited in that run.

**Not yet completed:** Phase 4.4.7 retrieval-efficiency improvements, an integrated authenticated Gradio frontend, comprehensive security/reliability and retrieval-quality evaluations, and production deployment. A locally functioning API is not equivalent to a deployed or independently security-audited service.

### Immediate next development checkpoint — Phase 4.4.7

1. Freeze the Phase 4.4.6 Git checkpoint and capture the real repository structure and current retrieval-service interfaces.
2. Build a small, repeatable synthetic insurance-policy question set and measure baseline retrieval relevance, redundant chunks, evidence coverage, citation validity, context size and latency.
3. Identify the highest-impact inefficiencies in the current per-document retrieval, reranking and context assembly path.
4. Implement small, reversible changes with focused tests, then rerun the full regression suite and compare against baseline measurements.
5. Document actual results and trade-offs; do not claim token, latency or accuracy gains without measurements.

**Scope boundary:** Phase 4.4.7 is retrieval optimization, not a redesign of authentication, document ownership, temporary storage or deployment. Its changes must preserve the Phase 4.4.6 security and cleanup behavior.

## Limitations and safety

- V3 is a **local prototype**, not a production-deployed multi-user service or a security-audited insurance platform.
- Scanned/image-only PDFs may require OCR; the current pipeline is designed for extractable text.
- Successful example citations do not guarantee factual correctness across arbitrary policy wording.
- No public deployment should use real customer documents without privacy controls, authorization review, operational retention/deletion policy, rate limiting, observability and security testing.
- Do not commit `.env`, JWT secrets, API keys, local database dumps, generated vector indexes or private insurance documents.
- The original Gradio/ML workflow remains in the repository, but V3's current focus is authenticated, persistent insurance-policy RAG. The detailed history of earlier versions belongs in Git history and engineering documentation rather than this V3 README.

## Engineering conventions

- Keep API, database, lifecycle and retrieval responsibilities separated into their existing modules.
- Make schema changes with new numbered migrations; never silently rewrite an applied migration.
- Use explicit authenticated owner/session parameters at service boundaries; never trust caller-provided document ownership.
- Preserve source/page metadata through chunking, retrieval and citation generation.
- Keep test data synthetic, use isolated databases for destructive integration tests, and review Git staging before commits.
- Record application defects, meaningful runtime warnings, root causes, fixes and verification evidence in the engineering record; do not treat mistakes in one-off diagnostic commands as application defects.

## Documentation

The project maintains separate engineering guides and issue logs covering retrieval experiments, PostgreSQL migration, authentication, document lifecycle, testing and decisions. Those documents provide the full historical rationale; this README describes the **current V3 implementation**.