# GenAI Health Risk & Cost Advisor — V3

**Status:** Local development prototype · **Branch:** `version_3` · **Verified through:** Phase 4.4.6A (31 October 2026) · **Current work:** Phase 4.4.7

An insurance analytics and policy-document intelligence project combining an existing scikit-learn insurance-cost prediction workflow with a FastAPI-based, retrieval-augmented generation (RAG) backend. Users can authenticate, upload text-based **insurance policy PDFs**, and ask evidence-grounded questions about one or more policies.

> **Disclaimer:** This is a research/portfolio prototype, not an insurance quotation, underwriting system, clinical diagnostic tool, or authoritative coverage determination. Check the original policy wording before making consequential decisions. Do not upload real customer data to an unreviewed deployment.

## Current capabilities

| Area | Implemented in V3 |
| --- | --- |
| Insurance-cost prediction | Existing trained scikit-learn pipeline for structured-input cost estimation; Gemini can explain the estimate and draft an advisory. The LLM does **not** calculate the numerical prediction. |
| Policy PDF ingestion | PDF text extraction, sentence-aware chunking, MiniLM embeddings, persistent per-document ChromaDB collections and PostgreSQL document registry. |
| Policy Q&A | Semantic retrieval, cross-encoder reranking, evidence/page citations, single- and multi-policy questions, and Gemini answer generation. Multi-policy selection/comparison and evidence attribution were exercised in Phase 3; broader answer-quality benchmarks remain planned. |
| Authentication | Registration, Argon2id password hashing, JWT access tokens, PostgreSQL-backed sessions, HttpOnly refresh cookie, refresh rotation and logout. Separate logins for two users and a second login session for one user were verified in manual API checks; simultaneous-load testing remains pending. |
| Authorization | Authenticated document endpoints enforce user and session ownership, including expiration checks. |
| Temporary document lifecycle | 30-minute inactivity expiration; cleanup on logout; optional scheduled cleanup every 600 seconds; PostgreSQL advisory locks coordinate document operations and deletion. |
| Backward compatibility | Pre-migration ownerless document records are preserved by cleanup but excluded from authenticated document access. |

**Current verification summary (31 October 2026):** Phase 4.4.6A technical verification is complete: **6 focused document-cleanup integration tests passed**, **40 integration tests passed**, and **252 tests passed** in the database-enabled full regression run. Manual testing also verified independent logins for two users and two sessions for one user, with cross-user and cross-session document isolation. The earlier **184 passed / 29 skipped** Phase 4.4.6 result and **205 passed / 29 skipped** 30 October result are retained below as dated historical checkpoints, not the latest overall result. Full concurrency/load testing is still planned for Phase 6.

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

## Project structure

The following is a **curated overview** of the current local V3 repository, based on the 31 October 2026 directory inventory. It intentionally omits generated files, private backups, local storage contents, and most individual test cases. See the sections below for implementation and verification details.

```text
GenAI-Health-Risk-Cost-Advisor/
├── api/                         # FastAPI app, authentication routes and dependencies
│   ├── main.py
│   ├── auth_routes.py
│   └── auth_dependencies.py
├── services/                    # Application and RAG business logic
│   ├── auth_service.py           # Authentication and related session services
│   ├── document_service.py       # Policy ingestion and document operations
│   ├── document_lifecycle.py     # Expiration and cleanup
│   ├── document_operation_lock.py
│   ├── rag_service.py            # Retrieval and grounded policy Q&A
│   ├── rag_metrics.py            # Phase 4.4.7 request-level measurements
│   ├── embedding_service.py
│   ├── vector_store_service.py
│   ├── database_service.py
│   └── ...                       # Other ML, advisory and session services
├── database/
│   ├── migrate.py                # Database migration runner
│   ├── schema.sql
│   └── migrations/               # Versioned migrations 001–007
├── tests/
│   ├── unit_tests/               # Authentication, lifecycle, security and metrics tests
│   ├── integration_tests/        # Isolated PostgreSQL and ChromaDB checks
│   ├── evaluation/               # Phase 4.4.7 synthetic evaluation questions
│   └── ...                       # API, retrieval and experiment tests
├── scripts/
│   └── benchmark_rag.py          # RAG benchmark utility
├── docs/
│   ├── engineering_issue_log/    # Engineering records
│   ├── sample_documents/         # Fictional insurance-policy PDFs
│   └── screenshots/              # Application screenshots
├── models/                       # Existing insurance prediction artifacts
├── notebooks/                    # Insurance-cost analysis notebook
├── data/                         # Dataset used by existing ML workflow
├── storage/                      # Local storage directory (contents not documented)
├── app.py                        # Existing Gradio application
├── config.py                     # Application configuration
├── insurance_transformers.py     # Existing ML preprocessing components
├── requirements.txt
├── .gitignore
└── README.md
```

**Repository hygiene:** Local PostgreSQL backup dumps, `.env` files, vector-store data, credentials, and temporary directory inventories should not be committed. The local `backups/` directory exists but is deliberately excluded from the public-facing tree. Verify `.gitignore` coverage before staging changes.

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
| **4.4.6A** | Multi-user and multi-session security verification, storage guards, and isolated cleanup integration checks. | **Complete — 31 October 2026; 40 integration tests and 252 database-enabled regression tests passed.** |
| **4.4.7** | Retrieval efficiency measurement and optimization (irrelevant chunks, prompt/context size, latency, citation quality). | **In progress — instrumentation and one live baseline measured; optimization pending.** |

### Phase 4.4.6 — Temporary document lifecycle (29 October checkpoint)

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

**Current checkpoint (31 October 2026):** The local V3 backend is verified through **Phase 4.4.6A**. Earlier 29 and 30 October checkpoints are preserved below as historical evidence. **Phase 4.4.7 is in progress:** initial instrumentation and one live baseline are recorded, while optimization is pending. Phases **5–8** remain future work. This is a milestone status, **not** a claim that the overall product is production-ready or a percentage-complete estimate.

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
| **4.4.6A — Multi-user and multi-session security verification** | Manual cross-user/cross-session API checks, isolated storage guards, cleanup and lock integration tests. | **Complete — 31 October 2026** |
| **4.4.7 — Retrieval efficiency** | Establish a repeatable baseline for irrelevant/redundant retrieved chunks, context size and estimated token use, retrieval/answer latency, coverage and citation correctness; optimize with measured trade-offs and regression protection. | **In progress — instrumentation and initial baseline complete; optimization pending** |
| **5 — Authenticated user interface** | Integrate Gradio with the authenticated FastAPI backend: register/login/logout, refresh handling, policy upload/list/selection, multi-policy Q&A, citations, expiry-aware UX and error states. | **Planned** |
| **6 — End-to-end reliability and security** | Validate full user journeys and failure recovery; concurrent user logins/sessions and overlapping upload/query/delete stress tests; multi-worker scheduler coordination; privacy/security review, negative authorization tests, robust error handling, structured logging/observability and operational safeguards. | **Planned** |
| **7 — Systematic RAG evaluation and performance** | Broader synthetic insurance-policy benchmark; retrieval relevance/coverage, citation faithfulness, answer correctness, latency and resource measurements; compare approaches and document limitations. | **Planned** |
| **8 — CI/CD and deployment** | Containerization as appropriate; GitHub Actions test/migration gates; durable database/vector storage; secret management; backup/restore; hosting-cost review; staging and remote smoke tests. | **Planned — deployment decisions not finalized** |

### What is working now versus what is still needed

**Implemented and locally verified:** insurance-cost prediction/advisory as an existing independent workflow; authenticated FastAPI insurance-policy ingestion and question answering; persistent semantic indexes; multi-policy citations; PostgreSQL-backed accounts/sessions; document isolation; inactivity expiry and deletion from both stores. The latest reported database-enabled full regression was **252 passed** on 31 October 2026; the earlier Phase 4.4.6 default checkpoint was **184 passed, 29 skipped, 0 failed**. The skipped cases were not individually audited in that earlier run.

**Not yet completed:** Phase 4.4.7 retrieval-efficiency improvements, an integrated authenticated Gradio frontend, comprehensive security/reliability and retrieval-quality evaluations, and production deployment. A locally functioning API is not equivalent to a deployed or independently security-audited service.

### Immediate next development checkpoint — Phase 4.4.7

1. Preserve the completed Phase 4.4.6A verification and commit it together with the Phase 4.4.7 instrumentation checkpoint; Phase 4.4.6 itself was committed on 29 October 2026.
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

## Phase 4.4.6A — Multi-user and multi-session security verification

**Verification date:** 30 October 2026
**Status:** Manual API security verification completed; isolated integration verification pending.
**Environment:** Local FastAPI, Swagger UI, PostgreSQL and ChromaDB.

### Objective

Verify that authenticated insurance-policy documents are isolated by both user identity and login session, preventing unauthorized document access and cross-user information leakage through RAG retrieval.

### Verification performed

Three independent Swagger browser sessions were used:

- **Swagger 1:** User A, first login session.
- **Swagger 2:** User B, separate user account.
- **Swagger 3:** User A, second independent login session.

The following checks were performed using fictional insurance-policy PDFs:

| Security check | Observed result |
|---|---|
| Authorized document upload and metadata retrieval | HTTP 201 for upload; HTTP 200 for owner access |
| Cross-user document metadata access | HTTP 404 — Document not found |
| Same-user, different-session document access | HTTP 404 — Document not found |
| Cross-user explicit-document RAG request | HTTP 404 — Document not found |
| Same-user cross-session RAG request | HTTP 404 — Document not found |
| User B's own RAG retrieval | Correct policy-specific answer with evidence from User B's document |
| Logout and access-token revocation | HTTP 200 logout, followed by HTTP 401 — Session is expired or revoked |
| Refreshed access-token authentication | HTTP 200 on authenticated document listing after refresh |
| Independent document uploads and retrieval | Successful across the tested sessions |

### Multi-user login and multi-document retrieval: verification scope

- **Separate user logins:** Manual testing on 30 October used User A and User B in independent authenticated Swagger sessions. A second login for User A created a separate session. Authorized requests succeeded for the respective sessions, while cross-user and cross-session document access and RAG requests were rejected. This establishes the tested multi-user/multi-session behavior; it is **not** a concurrent-load or high-traffic login test.
- **Multiple policy documents in one question:** The Phase 3 workflow supports selecting more than one authorized insurance-policy document for a single RAG question, retrieving relevant passages across the selected documents, and returning a combined or comparative answer with document/page evidence. Earlier Phase 3 synthetic-policy tests and citation checks support this capability. The 30 October security matrix primarily verified **isolation between users and sessions**, not a new comprehensive multi-policy answer-quality benchmark.
- **Next evaluation:** Phase 4.4.7 will measure retrieval/reranking relevance, coverage, citation attribution and latency for single- and multi-policy questions; Phase 7 will broaden answer-quality evaluation. Phase 6 owns concurrent-user/session and overlapping upload/query/delete stress testing.

### Test documents

The security tests used synthetic insurance-policy documents, including:

- `sample_insurance_policy_rag_test_v2.pdf` — basic policy verification.
- `sample_policy_v3_advanced.pdf` — User A's advanced policy.
- `sample_policy_security_user_b.pdf` — User B's fictional HorizonShield Silver policy, maintained under `docs/sample_documents/`.

User B's sample policy contains distinct coverage and deductible information, allowing retrieval isolation to be checked against User A's policy.

These PDFs contain fictional information and are intended for local testing only.

### Authentication behavior

The application uses short-lived JWT access tokens with a 900-second lifetime and HttpOnly refresh-token cookies.

Manual testing confirmed that a newly authenticated session could access protected endpoints and that logout could revoke the associated backend session, causing its previous access token to be rejected.

Swagger UI's **Authorize** state is independent of backend session revocation. Calling `POST /auth/logout` does not automatically clear the token displayed in Swagger UI. The future authenticated frontend should clear its local authentication state after successful logout.

### Automated regression

Command:

```bash
python -m pytest tests/ -q
```

Latest result:

```text
205 passed, 29 skipped in 7.88s
```

No test failures were reported.

The 29 skipped tests must not be interpreted as successful integration checks.

### Verification boundaries and remaining work

The manual checks establish authorization behavior for the tested users, sessions, documents and API requests. They do not constitute a complete security audit.

The following require further isolated automated verification:

- Reuse rejection of a previously rotated refresh token.
- True simultaneous document operations and concurrency handling.
- Session-specific cleanup and advisory-lock behavior under concurrent operations.
- Database-backed integration tests that were skipped in the default regression run.

Destructive integration tests must use a dedicated PostgreSQL test database and isolated ChromaDB storage, never the working application database.

**Phase 4.4.6A checkpoint (30 October, historical):** Manual multi-user and multi-session security verification completed. Default regression suite passed. The isolated integration checks pending at this checkpoint were subsequently completed on 31 October, as documented in the closure addendum below. Comprehensive concurrency/load and production-security validation remain future Phase 6 work.

---

## Progress addendum — 30–31 October 2026

> **Current status (31 October 2026):** Phase **4.4.6A core security and document-lifecycle verification completed locally**. Phase **4.4.7 is in progress**: performance instrumentation and one live baseline have been verified, but retrieval optimization and post-change full regression remain pending. The earlier milestone tables and the 30 October security section above are preserved as historical snapshots; this dated addendum supersedes their *current/next phase* wording without altering their original results.

### Phase 4.4.6A — Isolated integration verification and closure (31 October 2026)

**Objective:** Finish the isolated PostgreSQL/ChromaDB document-cleanup checks following the 30 October manual multi-user/multi-session API verification, without broadening the phase into a production security audit.

**Database permission diagnosis and repair:** The six cleanup integration tests initially failed at the cleanup candidate `SELECT` query with `psycopg.errors.InsufficientPrivilege: permission denied for table documents`. In the dedicated `health_rag_migration_test` database, the configured application role `health_rag_app` initially had `SELECT=False` and `DELETE=False` on `public.documents`, while `SELECT` on `public.user_sessions` was already available. A one-time, narrowly scoped repair granted `SELECT` and `DELETE` on `public.documents` to `health_rag_app` **in the test database only**. A second run confirmed all three required privileges were `True` and no further grants were needed. The one-time repair script was subsequently removed. This does **not** establish the privilege configuration of the working application database or production environment.

**Test isolation correction:** Two integration tests previously called `cleanup_expired_documents()` without a session filter. Those calls were changed to use the synthetic `session_a` created by each test, avoiding selection of unrelated expired records in the test database. This changes test scope, not the application's scheduled cleanup behavior.

**Reported local verification results:**

| Check | Observed result |
| --- | --- |
| Focused document-cleanup integration tests | **6 passed** |
| Entire integration test directory | **40 passed in 4.93 s** |
| Database-enabled complete test suite | **252 passed in 6.50 s** |
| PostgreSQL test-role privilege recheck | `documents SELECT=True`, `documents DELETE=True`, `user_sessions SELECT=True` |
| Initial Git whitespace check | Two trailing-space findings in the historical README section; formatting cleanup and final Git review pending |

The six cleanup cases verify preservation of an active document, removal of expired document metadata and vectors, session-specific cleanup, cleanup after session revocation, skip/retry around a held session advisory lock, and metadata preservation/retry when ChromaDB deletion fails. These are **local test results**, not proof of all possible races, failure modes or production deployment security.

**Closure decision:** The agreed **technical acceptance criteria for Phase 4.4.6A are met** based on the reported results. README/engineering-log review and an appropriate Git checkpoint are administrative closure tasks, not a reason to repeat the passing test batch. The 30 October manual API checks and their **205 passed / 29 skipped** default-suite checkpoint remain documented above as distinct historical evidence.

### Phase 4.4.7 — Performance instrumentation checkpoint (30 October 2026)

**Status:** In progress. Instrumentation and an initial authenticated live request were verified; optimization has not yet been demonstrated.

The existing RAG pipeline now includes request-local numerical metrics for vector search, cross-encoder reranking, context construction, Gemini generation and total RAG service time, along with passage and context-size counts. A dedicated INFO-level console handler in `services/rag_metrics.py` resolved the absence of performance logs in the FastAPI terminal without changing the public API response schema.

A fictional policy upload returned HTTP 201; an authenticated question about the annual deductible returned HTTP 200 and answered **INR 10,000 per policy year**, citing evidence **E1** and **E2**. One observed local request produced:

| Measurement | One-request baseline |
| --- | ---: |
| Total RAG service time | 5,648.624 ms |
| Vector search | 11.101 ms |
| Cross-encoder reranking | 2,336.733 ms |
| Context construction | 0.008 ms |
| Gemini generation | 3,200.873 ms |
| Retrieved candidates / supplied evidence passages | 6 / 6 |
| Context characters | 5,907 |
| Approximate context tokens | 1,477 |

Seven focused instrumentation tests passed. Earlier checkpoints recorded **212 passed / 29 skipped** for the default regression and **241 passed** for an opt-in database-inclusive run; the later **252 passed** suite is the 31 October Phase 4.4.6A closure run. The 1,477-token figure is a character-based estimate, not a model-tokenizer count. One request is not a statistically representative latency baseline. At the time of this original instrumentation checkpoint, a post-logger-change full regression had not been separately established; the later reported 31 October database-enabled suite passed 252 tests. Do not infer performance improvements from these measurements.

**Next Phase 4.4.7 work:** Repeat warm-request measurements; assess retrieval relevance, redundancy, evidence coverage and citation correctness using synthetic insurance-policy questions; make small reversible optimizations; compare measurements and rerun regressions.

### Phase 4.4.7 — Retrieval ranking, answer quality and latency evaluation plan

The project uses **MiniLM vector similarity retrieval followed by cross-encoder reranking** to select insurance-policy evidence before Gemini generates a grounded answer. Reranking is an existing pipeline stage; systematic ranking-quality benchmarking is **in progress/planned**, not a completed accuracy claim.

| Dimension | Parameter / check | Current status |
| --- | --- | --- |
| Retrieval candidates | Candidate passage count and evidence passages sent to the LLM | Instrumented; one observed request used 6 candidates / 6 evidence passages |
| Ranking effectiveness | Relevant passages near the top; planned Precision@k, Recall@k and/or MRR against labeled synthetic questions | Evaluation planned; no verified aggregate ranking scores yet |
| Evidence quality | Coverage of policy clauses needed for the question; redundant or irrelevant passages | To be evaluated with `tests/evaluation/phase447_questions.json` |
| Answer grounding | Whether the answer follows the retrieved policy text and correctly identifies evidence/page citations | One live deductible answer verified with E1/E2; systematic evaluation pending |
| Missing evidence | Whether the system avoids unsupported assertions when a policy does not answer the question | Evaluation planned |
| Vector retrieval latency | Time spent searching ChromaDB collections | Instrumented; one observed request: 11.101 ms |
| Cross-encoder reranking latency | Time spent ranking retrieved candidates | Instrumented; one observed request: 2,336.733 ms |
| Context assembly | Context construction time and prompt passage size | Instrumented; one observed request: 0.008 ms and 5,907 characters |
| Token usage | Approximate context tokens | Character-based estimate: ~1,477; not an exact provider-token count |
| Generation and total latency | Gemini generation time and end-to-end RAG service duration | Instrumented; one observed request: 3,200.873 ms and 5,648.624 ms respectively |

**Measurement interpretation:** These numbers describe a single observed authenticated policy question, not averages, p95 latency, speedup, or general retrieval quality. Repeat warm-request runs and benchmark multiple synthetic policies/questions before selecting ranking thresholds, retrieval depth (`top_k`) or optimization changes. Use `scripts/benchmark_rag.py` and the evaluation question set as the project locations for this work; their existence does not establish that a complete benchmark has already been executed.

### Deferred verification and roadmap ownership

These are **planned checks, not confirmed vulnerabilities**. Keep them in **Phase 6 — End-to-end reliability and security**, and review their status before production deployment:

| Deferred item | Planned phase | Reason for deferral |
| --- | --- | --- |
| Wider concurrent upload/question/delete stress tests and operation-lock entry-point audit | Phase 6 | Beyond the focused lock/cleanup integration checks |
| Multi-worker scheduler coordination and single-leader execution | Phase 6 / deployment readiness | Current scheduler targets local single-worker development |
| Scheduler restart resilience and physical deletion timing | Phase 6 | Requires controlled operational/failure scenarios |
| Broader PostgreSQL–ChromaDB partial-failure and retry recovery | Phase 6 | Existing test covers one simulated ChromaDB deletion failure |
| Working/production database-role privilege audit and least-privilege migration policy | Phase 6 / before deployment | Test-database grants do not verify production privileges |
| Full privacy/security review, rate limiting, operational retention and monitoring | Phase 6–8 / before deployment | Required before handling real customer documents |

**Version-control checkpoint:** Phase 4.4.6 was committed on 29 October 2026 (`0531b8c`, followed by README formatting commit `f98aefd`). Phase 4.4.6A verification changes and Phase 4.4.7 instrumentation/evaluation scaffolding may be committed together as a clearly labeled checkpoint; this does **not** mean Phase 4.4.7 optimization is complete. Review staged files and exclude backups, secrets and generated storage. A later commit should record measured Phase 4.4.7 optimization and final evaluation results.
