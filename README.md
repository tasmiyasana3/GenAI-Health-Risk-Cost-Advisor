# GenAI Health Risk & Cost Advisor — V3

**Status:** Local development prototype · **Branch:** `version_3` · **Verified through:** Phase 5.2.6C FastAPI-controlled execution boundary (8 November 2026) · **Last committed source:** `4818f23` (Phase 5.2.6B) · **Next:** Phase 5.2.6D–E resource authorization, adversarial closure and UI integration

An insurance analytics and policy-document intelligence project combining an existing scikit-learn insurance-cost prediction workflow with a FastAPI-based, retrieval-augmented generation (RAG) backend. Users can authenticate, upload text-based **insurance policy PDFs**, and ask evidence-grounded questions about one or more policies.

> **Disclaimer:** This is a research/portfolio prototype, not an insurance quotation, underwriting system, clinical diagnostic tool, or authoritative coverage determination. Check the original policy wording before making consequential decisions. Do not upload real customer data to an unreviewed deployment.

## Current capabilities

| Area | Implemented in V3 |
| --- | --- |
| Insurance-cost prediction | Existing trained scikit-learn pipeline for structured-input cost estimation; Gemini can explain the estimate and draft an advisory. The LLM does **not** calculate the numerical prediction. |
| Policy PDF ingestion | PDF text extraction, sentence-aware chunking, MiniLM embeddings, persistent per-document ChromaDB collections and PostgreSQL document registry. |
| Policy Q&A | Semantic retrieval, cross-encoder reranking, evidence/page citations, single- and multi-policy questions, and Gemini answer generation. Phase 4.4.7C adds deterministic multi-topic query planning, bounded per-policy/topic evidence selection, deduplication and global reranking. Broader answer-quality and citation-faithfulness benchmarks remain planned. |
| Authentication | Registration, Argon2id password hashing, JWT access tokens, PostgreSQL-backed sessions, HttpOnly refresh cookie, refresh rotation and logout. Separate logins for two users and a second login session for one user were verified in manual API checks; simultaneous-load testing remains pending. |
| Authorization | Authenticated document endpoints enforce user and session ownership, including expiration checks. |
| Temporary document lifecycle | 30-minute inactivity expiration; cleanup on logout; optional scheduled cleanup every 600 seconds; PostgreSQL advisory locks coordinate document operations and deletion. |
| Backward compatibility | Pre-migration ownerless document records are preserved by cleanup but excluded from authenticated document access. |
| Secured frontend HTTP boundary | Separate FastAPI/Gradio ASGI shell with opaque HttpOnly browser identity, server-side authentication credentials, trusted-Origin validation, backend-connected login/refresh/logout, browser identity rotation, and fail-closed Gradio routes. Interactive `/auth` registration and login UI is enabled; restricted Gradio events, queue, uploads and file routes remain blocked. |
| Phase 5.2.6B Gradio authentication and trusted session issuance | `GradioAuthenticationAdapter` integrates Gradio `auth_dependency` with the server-side browser binding. `TrustedGradioSessionIssuer` mints unpredictable browser-owned session hashes through `POST /frontend-gradio/session`, checks ownership and current local authentication, and rejects forged/cross-browser hashes. The Gradio browser client is **not yet consuming these hashes**; protected callbacks and resources remain blocked. |
| Phase 5.2.6C FastAPI-controlled protected execution | `GradioExecutionAuthorizer` checks current browser identity, server-issued hash ownership and server-held access credentials. `POST /frontend-gradio/execute` uses trusted-Origin and authenticated-cookie checks, a strict JSON request schema and small body limit, then reauthorizes immediately before its minimal protected verification operation. Native Gradio callbacks/queues and file/upload routes remain blocked; this is **not** a functioning policy dashboard or native queue implementation. |

**Phase 4.4.6A verification summary (31 October 2026):** Phase 4.4.6A technical verification is complete: **6 focused document-cleanup integration tests passed**, **40 integration tests passed**, and **252 tests passed** in the database-enabled full regression run. Manual testing also verified independent logins for two users and two sessions for one user, with cross-user and cross-session document isolation. The earlier **184 passed / 29 skipped** Phase 4.4.6 result and **205 passed / 29 skipped** 30 October result are retained below as dated historical checkpoints, not the latest overall result. Full concurrency/load testing is still planned for Phase 6.

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
├── frontend/                    # Restricted Gradio/FastAPI frontend and authentication boundary
│   ├── server.py                # /auth page, auth HTTP routes, ASGI body limit, mounted shell
│   ├── auth_page.py             # Browser authentication HTML/CSP-nonce rendering
│   ├── auth_coordinator.py      # Login, identity rotation, refresh access, logout
│   ├── auth_origin.py           # Trusted-Origin checks
│   ├── api_client.py            # Backend HTTP authentication client
│   ├── session_manager.py       # Server-side token lifecycle
│   ├── browser_session_binding.py
│   ├── http_session.py
│   ├── gradio_security.py       # Fail-closed native event/queue/file gate
│   ├── gradio_auth.py           # Authenticated Gradio shell dependency
│   ├── gradio_session_issuer.py # Server-issued browser-owned session hashes
│   ├── gradio_execution_authorizer.py # Current ownership/credential check
│   └── gradio_protected_callbacks.py # Prepared callback; not mounted/enabled
├── services/                    # Application and RAG business logic
│   ├── auth_service.py           # Authentication and related session services
│   ├── document_service.py       # Policy ingestion and document operations
│   ├── document_lifecycle.py     # Expiration and cleanup
│   ├── document_operation_lock.py
│   ├── rag_service.py            # Retrieval and grounded policy Q&A
│   ├── rag_metrics.py            # Phase 4.4.7 request-level measurements
│   ├── query_planning.py         # Phase 4.4.7C deterministic topic-aware queries
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
│   ├── integration_tests/        # Auth HTTP/Gradio security, isolated DB/vector checks
│   ├── evaluation/               # Phase 4.4.7 synthetic evaluation questions
│   └── ...                       # API, retrieval and experiment tests
├── scripts/
│   ├── smoke_tests/              # Local frontend authentication/security/refresh checks
│   ├── benchmark_rag.py          # RAG benchmark utility
│   └── capture_phase447_retrieval.py # Offline retrieval evidence capture
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
   -> build a deterministic retrieval plan for explicit multi-topic questions
   -> retrieve bounded semantic candidates from authorized policy collections
   -> deduplicate and cross-encoder rerank against the original question
   -> select bounded per-policy/topic evidence (hard context ceiling)
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
| **4.4.7A–B** | Performance instrumentation and 10-case synthetic retrieval baseline with offline evaluation and failure investigation. | **Baseline complete — 2 November 2026; 3 historical evidence regression tests passed.** |
| **4.4.7C** | Deterministic multi-topic query planning, bounded per-policy/topic retrieval and globally reranked evidence selection; synthetic before/after evaluation and regression tests. | **Complete — 3 November 2026; 266 passed, 35 skipped, 12 subtests passed in the full suite; 28 targeted tests passed in a subsequent local rerun.** |
| **5.2.4** | Server-side frontend authentication coordinator, backend-connected login/refresh/logout, Origin validation, opaque cookie and browser identity rotation. | **Verified 5 November 2026; guarded database-enabled suite 470 passed, 12 subtests passed.** |
| **5.2.5B** | Interactive `/auth` registration/login UI, safe errors, CSP/security headers, bounded auth request bodies through ASGI, and updated Gradio security tests. | **Verified 6 November 2026; new auth tests 28 passed, Gradio tests 38 passed, full default suite 464 passed, 35 skipped, 12 subtests passed.** |
| **5.2.6A–B** | Gradio 6.30.0 trust-boundary review; authenticated `auth_dependency`; browser-owned server-issued hashes, logout/rotation revocation and forged-hash rejection. | **Verified 7 November 2026; 15 targeted tests and 520 passed / 35 skipped / 12 subtests in the full suite; source commit `4818f23`, documentation commit `aca267b`.** |
| **5.2.6C** | FastAPI-controlled protected execution probe; per-request issuer ownership and credential authorization; default-deny native Gradio route regression tests. | **Verified 8 November 2026; focused 26 passed, full regression 546 passed / 35 skipped / 12 subtests; subsequently expanded integration test file 12 passed. Native callbacks/queue remain disabled.** |

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

The existing `app.py` Gradio workflow remains separate. Phase 5.2.5B enables the interactive authentication page, **not** protected Gradio callbacks or document workflows. For local HTTP development, set `API_BASE_URL=http://127.0.0.1:8000`, `FRONTEND_ALLOWED_ORIGIN=http://127.0.0.1:7860`, and `FRONTEND_COOKIE_SECURE=false`, then run `python -m uvicorn frontend.server:app --host 127.0.0.1 --port 7860`. Visit `http://127.0.0.1:7860/` to bootstrap an anonymous cookie and redirect to `/auth`; do not treat direct `/ui/` access as an authenticated workflow.

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

**Current checkpoint (8 November 2026):** Phase 5.2.6C FastAPI-controlled execution boundary and default-deny native Gradio security are locally verified: 26 focused tests passed, 546 passed / 35 skipped / 12 subtests in the last reported full regression, followed by 12 passed in the expanded integration test file. Native Gradio callbacks and queues are deliberately disabled. Phase 5.2.6D/E and Phase 5.3 remain to be implemented. Earlier checkpoints remain below as historical evidence. Later Phase 5 work and Phases 6–8 remain future work. This is a milestone status, **not** a claim that the overall product is production-ready or a percentage-complete estimate.

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
| **4.4.7 — Retrieval efficiency and evidence coverage** | Instrument request stages; evaluate 10 synthetic cases at K=6/K=16; implement deterministic multi-topic retrieval and bounded topic-aware evidence selection; compare frozen baseline and post-change results. | **4.4.7A–C complete — 3 November 2026; no Phase 4.4.7D** |
| **5 — Authenticated user interface** | Phase 5.1 architecture, 5.2.1–5.2.4 authentication foundations, 5.2.5B browser auth, 5.2.6A–B trusted session issuance and 5.2.6C FastAPI-controlled execution boundary are implemented; native Gradio event/queue/file routes and policy UI remain restricted. | **In progress — 5.2.6C locally verified; 5.2.6D/E and 5.3 pending** |
| **6 — End-to-end reliability and security** | Validate full user journeys and failure recovery; concurrent user logins/sessions and overlapping upload/query/delete stress tests; multi-worker scheduler coordination; privacy/security review, negative authorization tests, robust error handling, structured logging/observability and operational safeguards. | **Planned** |
| **7 — Systematic RAG evaluation and performance** | Broader synthetic insurance-policy benchmark; retrieval relevance/coverage, citation faithfulness, answer correctness, latency and resource measurements; compare approaches and document limitations. | **Planned** |
| **8 — CI/CD and deployment** | Containerization as appropriate; GitHub Actions test/migration gates; durable database/vector storage; secret management; backup/restore; hosting-cost review; staging and remote smoke tests. | **Planned — deployment decisions not finalized** |

### What is working now versus what is still needed

**Implemented and locally verified:** insurance-cost prediction/advisory as an existing independent workflow; authenticated FastAPI insurance-policy ingestion and question answering; persistent semantic indexes; multi-policy citations; PostgreSQL-backed accounts/sessions; document isolation; inactivity expiry and deletion from both stores; Phase 4.4.7C deterministic multi-topic retrieval and bounded evidence selection. The latest reported Phase 4.4.7C full-suite checkpoint is **266 passed, 35 skipped, 12 subtests passed** (3 November 2026). Historical checkpoints include **252 passed** on 31 October and **184 passed, 29 skipped** for Phase 4.4.6. Skipped cases are not counted as passes.

**Not yet completed:** authorized interactive Gradio callbacks and policy workflows (remaining Phase 5), comprehensive security/reliability validation (Phase 6), passage-level retrieval and answer/citation-quality evaluation (Phase 7), and CI/CD/deployment (Phase 8). A locally functioning API is not equivalent to a deployed or independently security-audited service.

### Phase 4.4.7 development checkpoints

1. **4.4.7A — Complete:** Instrument request-stage timing and context-size measurements; retain the single-request latency checkpoint as historical evidence.
2. **4.4.7B — Complete:** Capture 10 synthetic retrieval cases, evaluate K=6/K=16, investigate four weak broad-query cases, and retain an offline historical-baseline regression test (3 passed).
3. **4.4.7C — Complete (3 November 2026):** Adopted deterministic topic planning and bounded policy/topic retrieval rather than the proposed standalone round-robin evidence interleaver. Compared the frozen Phase B baseline against Phase C offline retrieval captures, added topic-planning and integration tests, and ran full regression verification.
4. **No Phase 4.4.7D:** The post-change capture, comparison and verification were completed within Phase 4.4.7C. The next phase is **5.1 — Authenticated UI architecture and API contract review**.
5. Do not claim token, latency, citation-faithfulness or answer-accuracy gains without corresponding measurements.

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

### Phase 4.4.7B — Synthetic retrieval baseline and investigation (2 November 2026)

**Status:** Retrieval baseline and focused investigation complete; no production retrieval algorithm changed in this subphase. The earlier Phase 4.4.7 instrumentation checkpoint above remains a dated historical record.

**Dataset and scope:** Ten synthetic questions covering two fictional insurance policies, including deductible, waiting period, room rent, exclusions, unspecified information, co-payment, ambulance limit, claim deadlines, unsupported premium, and policy summary. The captured offline results contain **130 ordered policy/page references**. The capture stores no policy passage text and does not call Gemini. Local policy-ID mappings are excluded from Git.

**Commands used for offline evaluation:**

```bash
python tests/evaluation/evaluate_rag.py --results tests/evaluation/phase447_retrieval_results.json --k 6
python tests/evaluation/evaluate_rag.py --results tests/evaluation/phase447_retrieval_results.json --k 16
python -m unittest discover -s tests/unit_tests -p "test_phase447_broad_retrieval_baseline.py" -v
```

| Captured-evidence metric | K=6 | K=16 |
| --- | ---: | ---: |
| Evaluated cases | 10 | 10 |
| Hit@K | 0.9000 | 1.0000 |
| Precision@K | 0.3167 | 0.1898 |
| Recall@K | 0.7500 | 1.0000 |
| MRR@K | 0.7333 | 0.7458 |

**Investigation:** The four broad-query cases (`exclusions`, `copayment`, `claim_deadlines`, `policy_summary`) used comprehensive retrieval rather than semantic relevance ranking. Their 16 captured chunks were grouped by source policy: 11 chunks from SampleCare followed by 5 from HorizonShield. Each case covered both expected policy/page evidence groups within K=16; some expected pages fell beyond K=6 because of document-grouped ordering. These ranking metrics are therefore **not directly comparable** between comprehensive and semantic retrieval modes. Page-level matching does not prove passage relevance, citation faithfulness, answer correctness, or actual abstention behavior.

**Focused verification (historical, 2 November):** `tests/unit_tests/test_phase447_broad_retrieval_baseline.py` passed **3/3** tests, checking presence of the four broad cases, expected policy/page coverage and nonempty captured evidence. This is a **frozen-data regression test**, not a live retrieval integration test. A separate experimental round-robin helper passed **6/6** unit tests but was **not adopted or committed**; its untracked module and test were subsequently removed after confirming no production dependency and rerunning 28 Phase C tests successfully.

**Historical next-step note (2 November):** This was the planned 4.4.7B-to-C transition. The actual 4.4.7C implementation, evaluation and regression verification were completed on 3 November; see the Phase 4.4.7C closure addendum below. A real token budget, broader answer-quality checks and deployment hardening remain open concerns.

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

**Version-control checkpoints:** Phase 4.4.6 was committed on 29 October 2026 (`0531b8c`, followed by README formatting commit `f98aefd`). The final Phase 4.4.7C implementation and verification were committed and pushed on 3 November 2026 as `4bf89c2` (`feat(rag): implemented deterministic multi-topic retrieval and validated evidence quality`). Review staged files and exclude backups, secrets and generated storage.


---

## Phase 4.4.7C — Deterministic multi-topic retrieval and verification closure (3 November 2026)

**Status:** Complete for the agreed local Phase C scope. **Next:** Phase 5.1 authenticated Gradio/FastAPI architecture and API-contract review. This is not a claim of production readiness, answer correctness or citation faithfulness.

### Decision and implementation

The Phase 4.4.7B investigation exposed early-document bias in broad/comprehensive queries. A standalone round-robin interleaver was considered and unit-tested but **not adopted**: changing only the order of already selected passages does not ensure that the needed policy topics were retrieved. Its untracked helper (`services/evidence_ordering.py`) and dedicated test (`tests/unit_tests/test_evidence_ordering.py`) were removed after checking that no tracked production module depended on them.

The implemented approach uses `services/query_planning.py` to deterministically expand explicit multi-topic insurance questions. `services/document_service.py` searches authorized document collections with bounded per-query candidate counts, deduplicates evidence, reranks candidates against the original question, and selects evidence using per-policy or per-policy/topic limits. `MULTI_MAX_CONTEXT_CHUNKS = 18` is a hard ceiling, **not a target** to fill with irrelevant passages. The existing user/session authorization, expiry and lifecycle-lock boundaries remain in place.

### Retrieval evaluation: frozen Phase B versus Phase C

Ten synthetic questions over two fictional insurance policies were evaluated with policy/page evidence-group proxies. These are **not** passage-level relevance judgments and do not establish generated-answer correctness or citation faithfulness.

| Offline retrieval metric | Phase B @6 | Phase C @6 | Phase B @16 | Phase C @16 |
| --- | ---: | ---: | ---: | ---: |
| Hit@K | 0.9000 | 1.0000 | 1.0000 | 1.0000 |
| Precision@K | 0.3167 | 0.3833 | 0.1898 | 0.3708 |
| Recall@K | 0.7500 | 1.0000 | 1.0000 | 1.0000 |
| MRR@K | 0.7333 | 1.0000 | 0.7458 | 1.0000 |

These improvements describe **only the defined synthetic offline retrieval benchmark**. They must not be generalized to all insurance policies or treated as evidence of better Gemini answers.

**Phase C retrieval-only performance capture:** median **248.49 ms**, P95 **2,489.65 ms**, and first cold request approximately **4,217.30 ms**, across 10 requests. No equivalent Phase B latency comparison was established; **no speedup is claimed**. These measurements exclude Gemini generation.

### Verification and committed artifacts

- Full reported Phase C regression: **266 passed, 35 skipped, 12 subtests passed**; skipped cases were not counted as successful checks.
- Subsequent focused rerun after removing the unused round-robin files: **28 passed in 1.02 s** (`test_query_planning.py`, `test_phase447c_topic_coverage.py`, `test_phase447_comprehensive_ordering.py`).
- Commit `4bf89c2` on `version_3` includes `services/document_service.py`, `services/query_planning.py`, `tests/evaluation/PHASE_447_COMPLETION.md`, `tests/evaluation/test_phase447c_topic_coverage.py`, `tests/integration_tests/test_phase447_comprehensive_ordering.py`, and `tests/unit_tests/test_query_planning.py`.
- Local `tests/evaluation/phase447c_performance.local.json` and `tests/evaluation/phase447c_retrieval_results.local.json` remain untracked local captures; do not commit them inadvertently.
- Phase C retrieval verification used **no Gemini calls**. Phase 7 owns systematic answer correctness, passage-level retrieval relevance, citation faithfulness and abstention evaluation.

## Detailed implementation roadmap — Phases 5–8

The following sections describe **planned work, not implemented features**. Each phase is reviewed and verified before it is marked complete. Phase 5 begins with architecture and API-contract inspection, not immediate frontend rewrites. The existing insurance-cost/risk ML workflow remains separate from contractual insurance-policy RAG. No Gemini API calls should be made during development or verification without explicit approval.

### Phase 5 — Authenticated Gradio user interface

**Objective:** Connect the existing Gradio experience to the authenticated FastAPI insurance-policy backend without weakening the security and temporary-document lifecycle established in Phase 4.

| Step | Planned work | Verification / decision gate |
| --- | --- | --- |
| **5.1 — Architecture and API contract review** | Inspect the actual `app.py`, `api/main.py`, authentication routes/dependencies, document endpoints, schemas, `document_service.py`, RAG services and independent ML/advisory services. Map existing request/response contracts, error responses, token/cookie behavior and startup/configuration boundaries. Decide whether the UI calls FastAPI over HTTP or shares selected backend services; document the rationale and smallest safe integration. | Written integration decision, endpoint/contract inventory, state and security boundaries, and explicit list of gaps; no code changes until review is complete. |
| **5.2 — Authentication and session-aware UI** | Implement registration and login where supported by the current API; authenticated request handling, access-token expiry/refresh behavior, logout and UI state reset. Handle expired/revoked sessions without exposing credentials or using global user state. Preserve the backend as the sole authorization authority. | Tests for successful and failed login, refresh/expiry, logout, session isolation and no cross-user leakage. Confirm cookie handling against actual API behavior. |
| **5.3 — Insurance-policy document management** | Add authenticated PDF upload, list, select, inspect status and delete flows. Show ready/failed/expired states and understandable validation errors. Respect ownership, per-session visibility, file limits and temporary-document expiry; do not retain document content in shared UI state. | Fictional-policy upload/list/select/delete checks; negative cases for unauthorized, expired, invalid, oversized or failed uploads as supported by the backend. |
| **5.4 — Evidence-grounded RAG Q&A** | Ask single-policy and multi-policy questions using authorized selected document IDs; display answer, filename/page evidence and citation identifiers. Handle no evidence, unsupported questions, malformed citations, retrieval failures and session expiry without inventing policy terms. | UI/API contract tests for evidence provenance, multi-topic questions, errors and abstention behavior; mock generation unless live Gemini use is explicitly approved. |
| **5.5 — Preserve insurance-cost/risk dashboard** | Keep the trained scikit-learn insurance-cost prediction and existing advisory experience usable alongside policy intelligence, with clearly separated inputs, results and explanations. Avoid presenting ML estimates as policy coverage, premiums or underwriting decisions. | Existing ML regression tests and UI checks; no unintended coupling to policy sessions or RAG documents. |
| **5.6 — Isolated end-to-end UI regression** | Exercise a minimal vertical slice first: login → select an existing authorized fictional policy → ask → backend-enforced retrieval → display answer/evidence. Expand to upload, multi-policy questions, logout, expiry and errors after the slice passes. Use isolated test PostgreSQL/ChromaDB and synthetic data. | Reproducible automated and targeted manual tests; record skips, mocks and untested paths separately. |
| **5.7 — Phase closure** | Review security, accessibility/usability, API compatibility, configuration, test results, issue log and README/handbook; commit and push only verified files. | Documented acceptance decision and remaining Phase 6–8 risks; no unsupported production-readiness claim. |

**Phase 5 sequencing:** Begin with **5.1**, then implement the smallest authenticated vertical slice. Expand incrementally only after verifying the preceding boundary. The exact UI transport and session-handling design remain decisions for 5.1, not assumptions already settled.

### Phase 6 — End-to-end security and reliability

| Step | Planned work | Verification / decision gate |
| --- | --- | --- |
| **6.1 — Threat model and trust boundaries** | Inventory assets, credentials, user/session boundaries, uploaded PDFs, model inputs, PostgreSQL/ChromaDB and external services. | Prioritized threat model with owners and test cases. |
| **6.2 — Negative authentication and authorization** | Test revoked/expired tokens, refresh replay, cross-user/cross-session document access and forged document IDs across all endpoints and UI paths. | Automated negative matrix; no unauthorized policy retrieval or deletion in tested cases. |
| **6.3 — Input, upload and prompt-injection defenses** | Review malformed/oversized PDFs, content limits, validation, hostile policy text, retrieval instructions embedded in documents and error disclosures. | Adversarial synthetic tests; policy text remains untrusted reference material. |
| **6.4 — Concurrency, lifecycle and cleanup** | Test overlapping upload/query/delete/logout, expiration races, PostgreSQL advisory locks, cleanup retries and scheduler restart/multi-worker coordination. | Controlled race/failure tests; documented single-worker versus multi-worker limits. |
| **6.5 — Cross-store consistency and recovery** | Simulate PostgreSQL/ChromaDB partial failures, incomplete indexing/deletion and retries; review migration and backup/restore behavior. | Recovery tests and reconciliation procedure; no silent claim of atomic cross-store transactions. |
| **6.6 — Operational safeguards** | Review timeouts, bounded retries, rate limiting, secrets, least-privilege database roles, structured redacted logs, health checks and observability. | Verified safeguards and documented deployment-dependent gaps. |
| **6.7 — Closure** | Consolidate security findings, regression evidence and issue-log updates. | Phase-specific acceptance review; independent audit remains a separate question. |

### Phase 7 — Expanded RAG evaluation and performance

| Step | Planned work | Verification / decision gate |
| --- | --- | --- |
| **7.1 — Versioned fictional benchmark** | Expand synthetic insurance policies/questions to include comparisons, exclusions, ambiguity, conflicts, missing terms and adversarial wording. | Reproducible dataset, labels and documented scope. |
| **7.2 — Passage-level retrieval quality** | Evaluate relevance and coverage at the actual passage level, not only Phase 4.4.7 page-group proxies. | Report Precision/Recall/MRR or suitable metrics with explicit label definitions. |
| **7.3 — Answer correctness and grounding** | Check whether answers faithfully reflect supplied policy evidence without inventing benefits or limits. | Case-level rubric and aggregate results, distinguishing human review from automated judgments. |
| **7.4 — Citation faithfulness** | Validate that cited evidence IDs, filenames, pages and passages support the specific claims made. | Traceable citation audit and failure categories. |
| **7.5 — Abstention and uncertainty** | Test missing, ambiguous and contradictory policy information; ensure unsupported answers are qualified or withheld. | Measured abstention behavior and documented limitations. |
| **7.6 — Controlled performance and regressions** | Separate cold/warm vector search, reranking, context assembly, generation and end-to-end latency; evaluate resource use and context budgets against comparable baselines. | Repeated measurements with environment, sample size and methodology; no unmeasured speedup or token-saving claims. |
| **7.7 — Evaluation report and closure** | Consolidate benchmark results, error analysis, thresholds, reproducibility instructions and outstanding risks. | Evidence-backed Phase 7 conclusion, not blanket model-accuracy claims. |

### Phase 8 — CI/CD, staging and deployment

| Step | Planned work | Verification / decision gate |
| --- | --- | --- |
| **8.1 — Deployment architecture review** | Select topology, hosting and persistence strategy for FastAPI, Gradio, PostgreSQL, ChromaDB and model dependencies; estimate costs and operational constraints. | Reviewed architecture and explicit hosting decision. |
| **8.2 — Continuous integration** | Add GitHub Actions or equivalent checks for formatting/linting, unit/integration tests, dependency validation and build gates, using isolated services where needed. | Passing CI on a clean checkout; secrets never embedded in workflows. |
| **8.3 — Configuration and secrets** | Separate development/test/staging settings; manage Gemini, JWT, database and cookie secrets securely. | Documented environment contract and no committed credentials. |
| **8.4 — Data durability and migrations** | Plan persistent PostgreSQL/ChromaDB volumes, schema migrations, backups, restore tests and data-retention/deletion procedures. | Staging migration and recovery evidence. |
| **8.5 — Staging deployment and smoke tests** | Deploy a nonproduction environment; verify authenticated UI, fictional PDF lifecycle, RAG evidence, ML dashboard and failure behavior. | Recorded staging smoke-test results; no real customer data by default. |
| **8.6 — Monitoring and operations** | Add health checks, safe logs, metrics, alerts, runbooks, cleanup/scheduler ownership and rollback procedures. | Operational checks and ownership documented. |
| **8.7 — Release review** | Reconcile security, privacy, performance, cost and recovery findings; decide whether any production launch is justified. | Explicit go/no-go decision. Local tests alone do not establish production readiness. |

**Current next action:** Reconcile Phase **5.2.4** documentation and engineering issue log, perform the pre-staging review, then stage and commit only verified scoped changes. Live refresh and restricted Gradio route checks have passed. Phase 5.2.5 adds the interactive authentication UI. Historical checkpoints remain unchanged.


---

## Phase 5.2.3B — Restricted frontend HTTP boundary (4 November 2026)

**Scope:** A separate FastAPI/Gradio ASGI frontend shell, not yet the interactive authenticated dashboard. The existing `app.py` remains a legacy development entry point and must not be exposed as the secured production frontend. The backend remains the authority for authentication, sessions and document access.

**Implementation:** `frontend/api_client.py` handles backend HTTP requests; `frontend/session_manager.py` manages server-side credentials; `frontend/session_binding.py` manages opaque registry handles; `frontend/browser_session_binding.py` maps server-issued browser identities; `frontend/http_session.py` issues and reads HttpOnly browser cookies; `frontend/gradio_security.py` applies a fail-closed mounted-route allowlist; `frontend/server.py` mounts a non-interactive Gradio shell. The HTTP gate permits the shell and narrowly scoped public static resources (including `/ui/theme.css` and `/ui/static/fonts/` for bundled `.woff`/`.woff2` files), while denying event, queue, upload, file, reset, and other unapproved routes. A Gradio `session_hash` is **not** an authentication credential.

**Local startup (no paid external services required):**

```bash
FRONTEND_COOKIE_SECURE=false python -m uvicorn frontend.server:app --host 127.0.0.1 --port 7860 --workers 1
```

**Historical Phase 5.2.3B behavior (4 November; superseded by Phase 5.2.5B):** Open **`http://127.0.0.1:7860/`**, **not** `/ui/` as the initial request. At that checkpoint the root endpoint issued the anonymous browser cookie and redirected to `/ui/`; the current redirect is `/auth`. Direct access to `/ui/` without a registered cookie correctly returns `401` with `Browser session required.` The frontend Swagger UI is intentionally disabled; backend API docs are separate at `http://127.0.0.1:8000/docs` when the backend is running.

**Final user-reported verification (4 November 2026):** HTTP security integration **37 passed**; frontend regression **80 passed** at the preceding checkpoint; complete project suite **377 passed, 35 skipped, 12 subtests passed**. The 35 skips are opt-in PostgreSQL integration tests, not passed checks. Browser verification confirmed the root-to-UI bootstrap and restricted Gradio shell. Direct `/ui/` access without a registered cookie returned `401` as designed. The bundled SourceSansPro font returned `200 OK` after the narrowly scoped allowlist correction. The HTTP tests verify the restrictive shell, **not** authenticated interactive Gradio event authorization.

**Closure decision:** Phase 5.2.3B is complete **only for the restricted, non-interactive HTTP boundary**. Interactive Gradio session/queue/file ownership and authenticated dashboard workflows are pending; no production-readiness claim is made.

**Deployment restrictions:** In-memory browser/session binding requires a single frontend worker; `FRONTEND_COOKIE_SECURE=false` is local HTTP only. Before enabling interactive Gradio operations, implement and adversarially test cookie/identity rotation, CSRF/origin checks, browser-to-Gradio session and queue-event ownership, file authorization, and backend-enforced access. Do not run live Gemini calls without explicit approval. See `docs/PHASE_5_ARCHITECTURE.md` for the phase boundaries and security acceptance criteria.


---

## Phase 5.2.4 — Backend-connected frontend HTTP authentication (5 November 2026)

**Status:** Implementation and technical verification complete on 5 November 2026. Documentation, issue-log reconciliation and scoped Git commit remain pending. This addendum updates the current state without overwriting earlier milestone records.

### Implementation

- `frontend/auth_coordinator.py`: coordinates backend login, server-side credential ownership, browser identity rotation, rollback on failed binding, logout and local cleanup. A concurrent-login test verifies the losing session is revoked.
- `frontend/auth_origin.py`: exact trusted-Origin validation for authentication-changing HTTP requests. `FRONTEND_ALLOWED_ORIGIN` must be configured; missing or foreign origins fail closed.
- `frontend/server.py`: `/frontend-auth/status`, `/frontend-auth/login`, `/frontend-auth/logout`; returns only non-sensitive status, rotates the opaque browser cookie on successful login, rejects invalid credentials with HTTP 401, maps backend availability failures to HTTP 503, and clears local browser access on attempted logout. Failed backend revocation is not reported as confirmed success.
- `frontend/api_client.py`, `frontend/session_manager.py`, `frontend/browser_session_binding.py`, `frontend/http_session.py` and `frontend/gradio_security.py` retain their earlier responsibilities. JWT access and refresh credentials remain on the frontend Python server; the browser receives only the opaque HttpOnly cookie.
- `scripts/smoke_tests/verify_frontend_auth.py`: reusable manual HTTP smoke test; prompts for disposable-account credentials without printing passwords or tokens. Requires running local frontend and backend; it is **not** an automatic pytest unit test.

### Verification performed

- B.3 focused coordinator, rollback, concurrent-login, origin and HTTP login security tests: **45 passed**.
- Existing frontend HTTP security regression: **44 passed**.
- B.4 logout/error classification tests: **13 passed**; combined frontend HTTP tests: **23 passed**.
- Opt-in PostgreSQL-backed authentication contract tests: **22 passed**, against the guarded `health_rag_migration_test` database.
- Database-enabled full regression: **470 passed, 12 subtests passed** (user-reported). Earlier default-skipped results remain historical, not failures.
- Running backend `http://127.0.0.1:8000`: Swagger and `/health` available; root `/` returns 404 because no backend root route is defined.
- Running secured frontend `http://127.0.0.1:7860/`: anonymous bootstrap redirects with HTTP 303 to `/ui/`, restricted shell renders, and `/frontend-auth/status` initially reports `false`.
- Real local frontend → FastAPI → PostgreSQL smoke test: login HTTP 200; browser identity rotated; status changed to `true`; logout HTTP 200; final status `false`.
- Reusable smoke script: **8/8 checks passed**, including two distinct anonymous browser identities, authenticated Browser A while Browser B remained unauthenticated, and logout/cookie invalidation.
- One older test account returned HTTP 401; another disposable account authenticated successfully. The first account's credentials/database history were not investigated and should not be described as a product defect.

### Remaining verification and security boundaries

- **Live frontend-triggered refresh verified:** `python -m scripts.smoke_tests.verify_frontend_refresh` passed **7/7 checks** with a disposable account, including real backend login, refresh completion, returned access token, refresh-cookie rotation, authenticated status, logout and browser invalidation. The first run exposed an overly strict test assertion: the access JWT may be byte-identical when issued in the same second because the backend does not include a `jti`. The smoke test was corrected to verify a returned token and actual refresh-token rotation without changing backend token generation.
- **Restricted Gradio security verified:** the dedicated smoke test passed **7/7 checks**, including intentional HTTP 403 denial of `/ui/static/js/iframeResizer.contentWindow.min.js`, queue, upload, file and event routes. The shell still renders. This is an accepted fail-closed restriction for the current non-interactive phase, not a reason to broadly allowlist `/ui/static/`. Reassess only if later authorized UI functionality requires this asset.
- Gradio callbacks, queue/event ownership, uploads and file access remain blocked pending Phases 5.2.5–5.2.6. No complete authenticated dashboard is claimed.
- Single-worker frontend is required by the in-memory browser/session registry. `FRONTEND_COOKIE_SECURE=false` is for local HTTP only. Production still needs HTTPS, appropriate CSRF/Origin policy, rate limiting, shared session storage if scaled, and further security review.
- No paid external APIs were needed for these checks; no live Gemini calls should run without explicit approval.
- **Final database-enabled regression:** `RUN_PHASE4_DB_TESTS=1 python -m pytest -q` reported **470 passed, 12 subtests passed in 15.42 s**. `python -m py_compile scripts/smoke_tests/verify_frontend_refresh.py` and `git diff --check` succeeded; Git exit codes were 0.
- **No Phase 5.2.4 commit is recorded in this update.** Stage only phase-related files after documentation and issue-log review; leave `docs/research/` and local evaluation result JSON files untracked unless explicitly approved.

### Local commands

```bash
# Terminal 1: backend
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000

# Terminal 2: secured frontend (local HTTP only)
export API_BASE_URL=http://127.0.0.1:8000
export FRONTEND_ALLOWED_ORIGIN=http://127.0.0.1:7860
export FRONTEND_COOKIE_SECURE=false
python -m uvicorn frontend.server:app --host 127.0.0.1 --port 7860

# Terminal 3: interactive, disposable-account smoke test
python -m scripts.smoke_tests.verify_frontend_auth
python -m scripts.smoke_tests.verify_frontend_refresh

# Guarded database regression; never point this at the working database
RUN_PHASE4_DB_TESTS=1 python -m pytest -q

git diff --check
git status -sb
```


## Phase 5.2.4 final verification addendum — 5 November 2026

**Technical acceptance:** COMPLETE for the local secured frontend HTTP authentication boundary; documentation and Git closure pending.

| Verification | Observed result |
| --- | --- |
| Frontend-to-backend login, browser isolation and logout smoke test | **8/8 passed** |
| Restricted Gradio security smoke test | **7/7 passed**; blocked static JS, queue, upload, file and event routes remain HTTP 403 |
| Live frontend-triggered refresh smoke test | **7/7 passed**; real refresh-token rotation and logout verified |
| Full guarded PostgreSQL regression | **470 passed, 12 subtests passed in 15.42 s** |
| Refresh smoke-test syntax and Git whitespace check | **Passed**, exit codes 0 |

The refresh smoke test initially assumed every new access JWT must differ from the prior token. `services/token_service.py` uses whole-second JWT timestamps and does not include `jti`; login and refresh in the same second may produce an identical access JWT. The test was corrected to validate the returned token and refresh-token rotation. No backend JWT changes were required. The refresh smoke test uses `python -m scripts.smoke_tests.verify_frontend_refresh` from the repository root.

The secured Gradio shell is intentionally non-interactive: event, queue, upload, file and unapproved static routes remain blocked until ownership checks are implemented in later phases. The observed iframe-resizer JavaScript 403 is accepted as fail-closed for this milestone; it does not demonstrate a broken login.

**Not included in Phase 5.2.4:** interactive login/registration controls, Gradio callback authorization, authenticated policy upload/Q&A UI, concurrent-load testing, production security audit or public deployment. No live Gemini requests were required for this verification.

**Git closure:** Do not stage `docs/research/`, `tests/evaluation/phase447c_performance.local.json`, or `tests/evaluation/phase447c_retrieval_results.local.json` as part of this milestone. Review the engineering issue log and staged diff before committing.


---

## Phase 5.2.5B — Interactive authentication UI and HTTP security hardening (6 November 2026)

**Status:** Implemented and locally verified for the defined HTTP authentication UI and restricted Gradio shell. This is not public-deployment approval or an authorization sign-off for interactive Gradio callbacks. This section supersedes earlier *current/next milestone* statements; earlier dated checkpoints are retained as historical records.

### Delivered behavior and component boundaries

- `frontend/auth_page.py` renders the browser-facing registration/login interface with a per-response Content Security Policy (CSP) script nonce. Browser JavaScript sends credentials to same-origin frontend authentication endpoints, not directly to the backend. The browser does not receive JWT access or refresh credentials.
- `frontend/server.py` serves `/auth` and the `/frontend-auth/register`, `/frontend-auth/login`, `/frontend-auth/status` and `/frontend-auth/logout` routes. The root `/` bootstraps an opaque HttpOnly browser identity and redirects to `/auth` (HTTP 303), replacing the historical `/ui/` landing redirect.
- `frontend/auth_coordinator.py`, `frontend/api_client.py`, `frontend/session_manager.py`, `frontend/browser_session_binding.py`, `frontend/http_session.py` and `frontend/auth_origin.py` retain server-side credential ownership, backend transport, per-browser binding, identity rotation, cookie handling and exact trusted-Origin enforcement. Backend PostgreSQL-backed session and policy-document authorization remain authoritative.
- The authentication page applies no-store and restrictive browser security headers. Registration creates an account but does not automatically authenticate the browser. Invalid/duplicate credentials and backend failures are mapped to safe browser-facing errors.
- Authentication POST request bodies are capped at **4,096 bytes** by ASGI middleware. Accepted bodies are replayed through the public ASGI `receive` interface; the prior private Starlette `request._body` assignment was removed. Oversized bodies return HTTP 413 before the authentication handler executes.
- `/ui/` remains a **restricted non-interactive shell**. Unapproved Gradio event, queue, upload and file-serving endpoints continue to fail closed. An anonymous browser identity alone is not proof of authenticated user authorization.

### Issue P5.2.5B-01 — Stale Gradio landing redirect assertion

**Observed:** 28 failures in `tests/integration_tests/test_gradio_security.py` stopped inside `bootstrap_browser()` before their protected-route assertions.

**Root cause:** The test helper still expected `GET /` to redirect to `/ui/`; Phase 5.2.5B deliberately redirects to `/auth`.

**Change:** Updated the helper to assert HTTP 303 with `Location: /auth` and added `test_root_redirects_to_authentication_page()`. Preserved existing checks for forged/missing cookies, unsafe methods, unapproved paths, protected Gradio endpoints and independent browser identities.

**Expected and observed:** Focused Gradio suite **38 passed**. Classification: resolved test compatibility regression, not proof of a protected-route security defect.

### Issue P5.2.5B-02 — Private Starlette request-body attribute

**Observed:** Request-size handling used `request._body = bytes(body)`, a private framework attribute.

**Root cause/risk:** Body consumption and replay depended on an internal Starlette implementation detail.

**Change:** Introduced pure ASGI body-size enforcement for authentication POST routes, with a 4,096-byte limit, early HTTP 413 rejection and accepted-body replay through ASGI `receive`. Added offline negative tests for oversized and malformed requests.

**Expected:** Oversized requests return 413; valid requests reach the existing validation/authentication flow; no private `_body` manipulation. **Observed:** The new 28-test authentication security suite and the full default regression suite passed. The exact grep/diff-check outputs were not separately reported with the final results.

### Verification evidence

| Test command / scope | User-reported result |
| --- | --- |
| `python -m pytest tests/integration_tests/test_phase525b_auth_security.py -q --tb=short` | **28 passed** |
| `python -m pytest tests/integration_tests/test_gradio_security.py -q --tb=short` | **38 passed** |
| `python -m pytest tests/ -q --tb=short` | **464 passed, 35 skipped, 12 subtests passed** |

The 28 new tests account for the increase from the preceding default-suite checkpoint of 436 to 464 passes. These tests use a mocked backend and do not require paid services. The earlier Phase 5.2.4 **470 passed, 12 subtests passed** result used the opt-in guarded PostgreSQL suite and is a distinct checkpoint; do not compare those totals as if they used identical test selection.

Manual checks during the authentication UI work included successful registration (201), login (200), logout (200), duplicate registration (409), post-logout sign-in state and browser-session isolation. Browser Back navigation behavior was observed but was not used as an authorization assertion.

### Remaining boundaries and next milestone

- **Phase 5.2.6:** Design, implement and adversarially verify authenticated Gradio event/queue/callback ownership, upload and file authorization, browser-to-Gradio session binding and cross-browser/session-hash resistance before enabling protected actions.
- **Phase 5.3:** Integrate the existing insurance-cost prediction/advisory and authenticated insurance-policy upload, selection, RAG and citation workflows.
- **Before public deployment:** Rate limiting, HTTPS and secure cookies, shared session storage if multi-worker, operational privacy/security review, concurrency/load tests and robust monitoring/recovery.
- Continue using synthetic policies and free/local verification. Do not initiate potentially chargeable Gemini calls or infrastructure without explicit approval.

### Version control

The Phase 5.2.5B source and tests were reported as committed before this README update. The commit hash and message were not supplied and are therefore not asserted here. Commit this documentation separately using a descriptive `docs:` subject; avoid staging `docs/research/` or local Phase 4.4.7C evaluation JSON files unless explicitly approved.


---

## Phase 5.2.6A–B — Authenticated Gradio boundary and trusted server-side sessions (7 November 2026)

**Status:** Phase 5.2.6A architecture/security contract and Phase 5.2.6B **server-side** authentication and session-issuance implementation are complete, locally tested, committed and pushed. **Commit:** `4818f23` (`feat(auth): complete Phase 5.2.6B trusted Gradio sessions`). This is **not** an end-to-end interactive Gradio authorization sign-off or production security certification. Earlier dated milestone statements are preserved above as history; this section supersedes their *current/next* wording.

### Implemented production components

| Component | Verified purpose | Security boundary |
| --- | --- | --- |
| `frontend/server.py` | Mounts Gradio with `auth_dependency`, protects `/ui/config`, and exposes `POST /frontend-gradio/session` for authenticated server-side issuance | Origin and browser authentication required for issuance; restricted Gradio event/queue/upload/file paths remain denied |
| `frontend/gradio_auth.py` | `GradioAuthenticationAdapter` resolves the opaque HttpOnly browser identity to an authenticated server-side session for Gradio | Returns browser identity only; never sends backend access/refresh tokens to the browser |
| `frontend/browser_session_binding.py` | Maps independently authenticated browser identities to credential managers; includes authenticated Gradio ownership primitives | Prevents anonymous ownership checks and rejects cross-browser bindings; client-supplied session hashes alone do not establish trusted provenance |
| `frontend/gradio_session_issuer.py` | `TrustedGradioSessionIssuer` mints `secrets.token_urlsafe(32)` identifiers, tracks browser ownership, caps issuance per browser, verifies current local authentication, and supports revocation | Hashes are routing identifiers, **not** independent authorization credentials; issuer state is process-local |
| `frontend/gradio_security.py` and `frontend/http_session.py` | Existing fail-closed Gradio route restrictions and opaque-cookie validation | Event, queue, upload, and file-serving routes are still blocked until complete authorization is verified |

### Trusted session issuance flow

```text
Browser (opaque HttpOnly identity cookie)
    | POST /frontend-gradio/session + trusted Origin
    v
Frontend FastAPI boundary
    | GradioAuthenticationAdapter -> BrowserSessionBinding.resolve()
    v
TrustedGradioSessionIssuer.issue(authenticated_identity)
    | server generates unpredictable hash; records hash -> browser identity
    v
JSON {"session_hash": "..."} (Cache-Control: no-store)

Future authorized event: cookie + hash -> issuer.verify() ->
execution-time Gradio callback authorization (NOT YET ENABLED)
```

The issuance endpoint does not accept a browser-provided hash as proof of ownership. The authenticated browser may see the issued hash, but it does not receive the JWT, refresh token, or `SessionCredentialManager`. Logout explicitly revokes issued hashes; browser identity rotation and local session termination also cause subsequent verification to fail. Issuer verification **does not independently query the backend** to detect remote PostgreSQL revocation; backend authorization remains authoritative for backend operations.

### Test coverage and observed evidence

| Check | Result |
| --- | --- |
| New issuer unit and endpoint integration tests | **15 passed** |
| Full default local test suite (`python -m pytest tests/ -q --tb=short`) | **520 passed, 35 skipped, 12 subtests passed** |
| `python -m compileall -q frontend` and `git diff --check` | No errors reported |
| Git commit and remote branch | `4818f23` on `HEAD -> version_3, origin/version_3` |

The full-suite result is the user's Mac result. The 35 skipped tests must not be represented as executed/passed; opt-in database and live service tests have different prerequisites. The new tests are local and do not invoke paid LLM APIs.

### Security acceptance and explicit exclusions

- **Accepted for Phase 5.2.6B:** server-side Gradio auth adapter, production wiring, local browser/session ownership primitives, trusted server-generated issuance, forged/cross-browser rejection, logout/rotation invalidation, and restricted-route regression coverage.
- **Not yet accepted:** Gradio browser/client adoption of the server-issued hash; actual callback and queue execution-time checks; delayed-event and logout race protections; authenticated upload/download/file serving; end-to-end policy RAG UI; multi-worker deployment; live backend revocation propagation; production security audit.
- **Next — Phase 5.2.6C:** establish the trusted browser-to-Gradio event flow and authorize each callback/queue execution against current cookie identity, issued hash ownership, and session validity. Preserve fail-closed behavior until adversarial tests pass.
- **Then — Phase 5.2.6D/E:** protect uploads/files and document ownership; perform consolidated adversarial/regression review and issue-log/documentation closure.
- **Then — Phase 5.3:** connect authenticated insurance-cost/advisory and insurance-policy upload/RAG/citations to the interactive frontend.

### Engineering decisions and risk log

1. **Client-supplied session-hash provenance:** Existing `bind_authenticated_gradio_session()` can check authentication but does not establish that a browser-chosen hash was server-issued. **Mitigation implemented:** separate `TrustedGradioSessionIssuer`; **remaining:** integrate issued identifiers with the real Gradio client and event transport.
2. **Gradio authorization versus backend authorization:** `auth_dependency` authenticates the browser for Gradio, but is not by itself execution-time callback authorization. **Decision:** keep interactive routes denied until explicit per-event checks exist.
3. **Process-local state:** issuer and credential bindings are in memory. **Decision:** single frontend worker for local prototype; shared state and atomic multi-worker semantics require a separate design before scaling.
4. **Revocation:** local logout/rotation invalidates issued hash verification; issuer checks do not independently confirm remote backend revocation. **Decision:** retain backend session validation for protected API calls; cover remote revocation and race behavior in later tests.
5. **Resource limits:** issuance is capped per authenticated browser (default eight). This is not a comprehensive rate-limit, CSRF, or resource-exhaustion defense for public deployment.

**Documentation-only Git follow-up:** The source commit `4818f23` is already pushed. Commit the README and architecture documentation separately with `docs:` after reviewing the staged diff. Keep `docs/research/` and the two `tests/evaluation/phase447c_*.local.json` files untracked unless explicitly approved.

Phase 5.2.6C SECURITY BOUNDARY — SAFE INCREMENT, NOT FINAL GRADIO EVENT INTEGRATION

This package contains COMPLETE replacement frontend/server.py and unchanged
frontend/gradio_security.py for comparison. It adds a FastAPI-controlled
protected probe /frontend-gradio/execute. It deliberately leaves Gradio
callback, queue, file and upload routes BLOCKED. Do not claim that full
Gradio interactive execution is complete.

Prerequisite: frontend/gradio_execution_authorizer.py already created by user.

To use, copy the complete server.py replacement into your project, preserving
backups. Run new integration tests and full suite after modifications.

No Git staging/commit until Phase 5.2.6E.

---

## Phase 5.2.6C — FastAPI-controlled execution security and native Gradio default-deny verification (8 November 2026)

**Status:** Implemented and locally regression-tested **within the FastAPI-controlled boundary only**. Phase 5.2.6A–B were already documented above and committed (`4818f23` source, `aca267b` documentation). Phase 5.2.6C changes are not yet committed at the time of this documentation update. This milestone **does not complete all of Phase 5.2.6**: D/E remain pending.

### Security problem and design choice

Gradio 6.30.0 uses a browser-provided `session_hash` for its native callback and queue routing. That identifier is **not an authentication credential** and cannot prove that the requesting browser owns the server-side login session. Simply opening `/ui/call/*` or `/ui/queue/join` would risk entering Gradio's preprocessing, validator, cache or queue paths before authorization, and delayed jobs would require reauthorization after logout. The team therefore **did not enable native Gradio events or attempt an undocumented browser JavaScript hash override**.

Instead, the project uses a narrowly scoped **FastAPI-controlled** endpoint and keeps the native Gradio event, queue, upload and file-serving routes denied by the existing gate. This avoids treating a client-generated Gradio routing identifier as trusted proof of identity. The protected operation currently returns only a minimal session-verification result, not policy upload, prediction, retrieval or Q&A.

### Implemented request journey

```text
Browser with opaque HttpOnly cookie
  -> POST /frontend-gradio/session (authenticated, trusted Origin)
  -> TrustedGradioSessionIssuer issues random browser-owned session_hash
  -> POST /frontend-gradio/execute (trusted Origin + authenticated cookie)
       -> require application/json and exact {"session_hash": "..."} shape
       -> reject oversized (>256-byte) or invalid request bodies
       -> GradioExecutionAuthorizer.authorize(identity, session_hash)
            -> issuer.verify: current browser ownership + live local binding
            -> SessionCredentialManager.get_access_token()
       -> {"verified": true} with no-store and defensive response headers

Native /ui/call/*, /ui/queue/*, /ui/upload*, /ui/file* remain blocked.
```

**Files involved:** `frontend/server.py` (endpoint and dependency wiring), `frontend/gradio_execution_authorizer.py` (ownership/credential verification), `frontend/gradio_session_issuer.py` (existing B-phase issuer), `frontend/gradio_auth.py` (existing browser authentication), `frontend/gradio_security.py` (unchanged deny-by-default route gate), and `frontend/gradio_protected_callbacks.py` (prepared but **not wired to native Gradio**). The browser authentication page `frontend/auth_page.py` did not need an undocumented Gradio client-side hash override.

### Verification evidence (user-reported, 8 November 2026)

| Verification | Result | Interpretation |
| --- | --- | --- |
| Focused Phase 5.2.6C tests | **26 passed** | Reported targeted security and callback/authorizer tests |
| Full regression after the C implementation | **546 passed, 35 skipped, 12 subtests passed** | No failures reported in executed tests; skips are not passes |
| Expanded `test_phase526c_secure_execution_boundary.py` | **12 passed** | Includes four new parametrized anonymous native-route rejection cases |
| Manual unauthenticated native-route probes | **HTTP 401** for all four routes | Confirms denial of the tested anonymous requests, not native callback safety |

The four manually observed denial routes were `POST /ui/queue/join`, `POST /ui/call/v2/verify_session`, `POST /ui/call/verify_session`, and `GET /ui/queue/data?session_hash=forged`. The integration suite also contains an authenticated native-route denial assertion. The **12-test rerun occurred after** the last reported 546-test full-suite checkpoint; no new full-suite total is asserted for that later change.

### Accepted protections and remaining risks

- **Implemented and tested within current scope:** server-issued hash verification against authenticated browser ownership; current local credential availability; trusted-Origin and request-schema checks at the FastAPI-controlled boundary; denied anonymous native event/queue routes; unchanged fail-closed native gate; no backend JWT/refresh credentials returned to browser.
- **Not implemented or proven:** native Gradio callback execution, queue admission/preprocessing authorization, delayed queued-job revocation checks, per-event queue-result ownership, native file/upload authorization, interactive insurance-policy UI, full concurrency/remote-revocation testing, rate limiting or independent security audit.
- **Single-worker assumption:** browser bindings, credential managers and issuer ownership maps are process-local. Multiple workers require shared state and reviewed revocation/atomicity semantics.
- **Backend remains authoritative:** a frontend verification result does not independently prove a PostgreSQL-backed backend session is active. Backend APIs must still validate JWT, current database session, and policy document user/session ownership.

### Reproducible local tests (free; no Gemini calls)

```bash
python -m pytest tests/integration_tests/test_phase526c_secure_execution_boundary.py -q
python -m pytest tests/unit_tests/test_gradio_execution_authorizer.py tests/unit_tests/test_gradio_protected_callbacks.py -q
python -m pytest -q
```

Use isolated test services as specified by the test fixtures. Do not run destructive opt-in database integration tests against the working application database.

### Engineering decision / next milestone

**Decision:** Keep the FastAPI-controlled execution boundary as the active protected path; native Gradio callback/queue routes remain **intentionally disabled and regression-tested**. Enabling them in a future phase requires separately demonstrated admission-time ownership authorization, execution-time reauthorization, queue-result isolation and logout/expiry race tests. Phase **5.2.6D** must address authenticated PDF upload and resource access, and **5.2.6E** must reconcile adversarial verification, issue log and phase closure. Phase **5.3** remains the interactive insurance-cost and policy intelligence workflow integration. No paid services are needed for this verification.
