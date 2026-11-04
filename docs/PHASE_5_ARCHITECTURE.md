
# Phase 5 — Authenticated Frontend Architecture

**Project:** GenAI Health Risk & Cost Advisor V3
**Branch:** `version_3`
**Frontend:** Gradio 6.30.0
**Backend:** FastAPI
**Updated:** 4 November 2026
**Document status:** Living architecture and verification record
**Current milestone:** Phase 5.2.3B completed
**Next milestone:** Phase 5.2.4 — Backend authentication integration

---

## 1. Purpose

Phase 5 connects the Gradio frontend to the authenticated
FastAPI backend while preserving browser-session isolation,
server-side credentials, and insurance-policy document
authorization.

The target application supports:

- User registration, login, refresh, and logout.
- Insurance cost prediction.
- Health-risk and insurance-cost advisory.
- Insurance-policy PDF upload and management.
- Authenticated insurance-policy retrieval and RAG.
- Server-side session and credential management.

The frontend must not bypass backend authorization.

Implementation and testing should prioritize local,
free resources. Potentially chargeable API calls require
explicit approval before execution.

## 2. Architectural principles

1. Gradio handles presentation and user interaction.
2. FastAPI remains the authentication and authorization authority.
3. Authentication credentials remain on the Python server.
4. Anonymous browser identity is distinct from authentication.
5. Browser-provided identifiers are untrusted.
6. Gradio session hashes are not authentication credentials.
7. Registry handles are never exposed as browser credentials.
8. Independent browsers must have isolated authentication state.
9. Every protected resource requires authorization.
10. Unknown or unverifiable ownership fails closed.
11. Login rotates the browser identity.
12. Logout clears local state and requests backend revocation.
13. HTTP security requires adversarial tests.
14. The initial frontend deployment uses one worker.
15. Existing backend and ML/RAG services remain authoritative.
16. Disabled endpoints must not be described as authorized endpoints.
17. Passing local tests does not establish production readiness.

## 3. Target architecture

```text
Browser
  |
  | HttpOnly browser identity cookie
  v
Frontend ASGI Server
  |
  +-- HTTP session validation
  +-- Gradio route authorization
  +-- Resource ownership verification
  |
  v
BrowserSessionBinding
  |
  v
SessionRegistry
  |
  v
SessionCredentialManager
  |
  v
FrontendAPIClient
  |
  | Authenticated HTTP
  v
FastAPI Backend
  |
  +-- Registration / login / refresh / logout
  +-- JWT and active-session validation
  +-- PostgreSQL users and sessions
  +-- Document ownership checks
  +-- Insurance prediction and advisory
  +-- Insurance-policy document services
  +-- Retrieval and RAG
         |
         +-- ChromaDB
         +-- Embeddings and reranking
         +-- Gemini, when approved
```

This is the target architecture.

Phase 5.2.3B implements the restricted frontend HTTP
boundary, not the complete interactive architecture.

## 4. Component responsibilities

### 4.1 Frontend API client

File: `frontend/api_client.py`

Responsibilities:

- Registration and login HTTP requests.
- Refresh and logout requests.
- HTTP timeouts and error handling.
- Authentication response validation.
- Backend refresh-cookie transport.
- Explicit HTTP client lifecycle management.

The API client transports requests but does not establish
browser ownership or replace backend authorization.

### 4.2 Credential manager

File: `frontend/session_manager.py`

Responsibilities:

- Hold access and refresh credentials server-side.
- Track access-token expiration.
- Refresh credentials when required.
- Serialize concurrent refresh attempts.
- Replace rotated credentials safely.
- Request backend logout.
- Clear credentials on termination.

The credential manager must not determine browser ownership.

### 4.3 Session registry

File: `frontend/session_binding.py`

Responsibilities:

- Create unpredictable internal registry handles.
- Associate handles with credential managers.
- Enforce idle expiration.
- Synchronize registry operations.
- Remove expired managers.
- Clear local state during cleanup.

Registry handles are internal identifiers.

The implementation is in-memory and single-process.

### 4.4 Browser session binding

File: `frontend/browser_session_binding.py`

Responsibilities:

- Create anonymous browser identities.
- Associate authenticated credential managers after login.
- Rotate identities during authentication.
- Resolve credentials for verified browser identities.
- Track Gradio-session ownership.
- Reject mismatched ownership.
- Remove ownership on termination.
- Clear local mappings on shutdown.

Browser identities and Gradio session hashes have
different responsibilities.

The existence of an ownership mapping alone does not
prove the HTTP request legitimately owns a resource.

### 4.5 HTTP session cookies

File: `frontend/http_session.py`

Responsibilities:

- Read browser-session cookies.
- Reject unregistered identities.
- Issue server-controlled cookies.
- Clear cookies on termination.
- Apply cookie security attributes and lifetime settings.

Cookie policy:

- HttpOnly: enabled.
- SameSite: Strict.
- Secure: enabled for HTTPS production.
- Secure=false: local HTTP testing only.
- Path: `/`.
- Lifetime: bounded by configuration.

An anonymous browser cookie is not a JWT.

A browser cookie is a bearer secret and must be
protected with HTTPS and appropriate request safeguards.

### 4.6 Gradio HTTP security gate

File: `frontend/gradio_security.py`

The restricted implementation enforces an explicit
allowlist around the mounted Gradio application.

Permitted with a registered browser identity:

- GET/HEAD for `/ui` and `/ui/`.
- GET/HEAD for `/ui/theme.css`.
- GET/HEAD for the designated bundled `/ui/assets/` paths.
- GET/HEAD for bundled `.woff` and `.woff2` resources
  under `/ui/static/fonts/`.

Blocked:

- Gradio event execution.
- Queue submission.
- Queue result streams.
- Upload endpoints.
- Private file retrieval.
- Session heartbeat and reset routes.
- Unknown mounted routes.
- Unsafe HTTP methods.

The gate denies requests it cannot authorize.

The static-resource allowlist is deliberately narrower
than allowing all `/ui/static/` paths.

The public asset directories must still be reviewed
before production deployment to ensure they cannot
serve private or user-controlled content.

This module does not authorize interactive Gradio events.

### 4.7 Frontend ASGI server

File: `frontend/server.py`

Responsibilities:

- Initialize SessionRegistry.
- Initialize BrowserSessionBinding.
- Configure HTTP session cookies.
- Apply Gradio HTTP security middleware.
- Bootstrap anonymous browser sessions.
- Mount the restricted Gradio shell.
- Provide a minimal health endpoint.

The restricted server does not import the legacy
prediction and RAG callbacks from `app.py`.

This prevents the restricted public entry point
from exposing those direct-service operations.

### 4.8 Legacy Gradio application

File: `app.py`

The existing Gradio application remains a development
entry point.

It must not be treated as the secured production frontend.

Before public interactive deployment, protected callbacks
must use authenticated backend HTTP operations and
enforce browser/resource ownership.

### 4.9 FastAPI backend

Relevant files include:

- `api/main.py`
- `api/auth_routes.py`
- Existing authentication dependencies.
- Existing document authorization services.

Responsibilities:

- Registration and password authentication.
- JWT issuance and validation.
- Refresh-token rotation.
- Active-session verification.
- Backend session revocation.
- Protected document operations.
- Document ownership enforcement.
- Prediction and RAG API operations.

Frontend authentication supplements but never replaces
backend authorization.

## 5. Three security enforcement layers

### Layer 1 — Browser HTTP boundary

Files:

- `frontend/http_session.py`
- `frontend/gradio_security.py`
- `frontend/server.py`

Implemented for the restricted shell:

- Server-issued anonymous browser identities.
- Registered-cookie validation.
- Missing-cookie rejection.
- Forged-cookie rejection.
- Read-only route allowlist.
- Fail-closed blocking of unapproved Gradio operations.

Pending for the interactive application:

- HTTP login identity rotation.
- Logout cookie invalidation.
- Origin and CSRF protections for enabled mutations.
- Production HTTPS and reverse-proxy verification.

### Layer 2 — Gradio resource ownership

Files:

- `frontend/browser_session_binding.py`
- `frontend/gradio_security.py`
- Future interactive resource-authorization integration.

Required before enabling protected Gradio operations:

- Verified browser-to-Gradio session ownership.
- Queue-event ownership.
- Stream-result ownership.
- Upload and private-file ownership.
- Cross-browser session isolation.
- Expiration and cleanup.
- Adversarial HTTP verification.

Current status:

Ownership primitives are unit-tested.

Interactive resource routes remain blocked.

A valid cookie must never authorize arbitrary
session hashes, event identifiers, or files.

### Layer 3 — Backend authorization

Files:

- Existing FastAPI authentication dependencies.
- Existing backend authorization services.
- `frontend/api_client.py`.
- Future authenticated Gradio callbacks.

Required controls:

- Valid access token.
- Valid active backend session.
- Appropriate authenticated user.
- Document and session ownership.
- Document readiness and expiration.
- Permission for the requested operation.

The frontend must not bypass this layer.

## 6. Authentication lifecycle

### 6.1 Anonymous browser bootstrap

Expected sequence:

```text
GET /
  |
  +-- Check registered browser identity
  +-- Create anonymous identity if missing
  +-- Set HttpOnly cookie
  |
  v
303 Redirect to /ui/
  |
  v
GET /ui/ with cookie
  |
  v
200 Restricted Gradio shell
```

The correct initial browser URL is:

`http://127.0.0.1:7860/`

Direct access to `/ui/` without a registered cookie
must return HTTP 401.

The anonymous session does not contain backend
authentication credentials.

### 6.2 Registration — pending UI integration

1. User submits registration details.
2. FrontendAPIClient calls FastAPI registration.
3. Backend validates and creates the account.
4. Frontend displays the result.

Registration does not automatically imply login unless
the backend contract explicitly provides that behavior.

### 6.3 Login — pending UI integration

1. User submits credentials.
2. FrontendAPIClient calls FastAPI login.
3. Backend authenticates the user.
4. Frontend creates a SessionCredentialManager.
5. BrowserSessionBinding rotates the browser identity.
6. A replacement HttpOnly cookie is issued.
7. Previous identity and ownership records are invalidated.
8. Browser receives only non-secret UI status.

Actual login UI integration belongs to Phase 5.2.5.

### 6.4 Protected request — pending integration

1. Validate browser identity.
2. Verify resource ownership.
3. Resolve the authenticated credential manager.
4. Obtain or refresh the access token.
5. Call FastAPI through FrontendAPIClient.
6. Backend authenticates the request.
7. Backend checks resource authorization.
8. Return only authorized results.

### 6.5 Refresh

Refresh is managed server-side.

Concurrent refresh attempts must be synchronized.

Rotated credentials must replace previous credentials
consistently.

Failed refresh must invalidate local authentication.

### 6.6 Logout

Logout must:

1. Resolve the verified browser session.
2. Request backend revocation.
3. Clear local credentials.
4. Remove resource ownership.
5. Expire the browser cookie.
6. Reset the UI.

Local cleanup alone does not establish backend revocation.

### 6.7 Expiration and cleanup

Frontend registry expiration and cookie expiration
must be coordinated.

Expired credentials must be cleared locally.

A frontend process restart clears in-memory state.

Backend sessions may survive frontend restart until
backend expiration or revocation.

## 7. Gradio-specific security findings

Inspected Gradio version: 6.30.0.

Relevant mechanisms include:

- `gr.Request`
- `gr.State`
- Gradio session hashes.
- Queue and event routes.
- StateHolder.
- Heartbeat and unload behavior.
- File-serving routes.

Gradio uses session identifiers for UI state.

A session hash is not an authentication credential.

Different Gradio endpoints have different request
and authorization paths.

Callback-level authentication alone cannot establish
ownership of queue streams, uploaded files, or every
session-related resource.

Therefore:

- Never resolve JWTs using session_hash alone.
- Never expose registry handles to the browser.
- Never treat first-claim-wins ownership as sufficient proof.
- Validate ownership at the relevant HTTP boundary.
- Keep unverifiable endpoints disabled.
- Test cross-browser access before enabling them.

## 8. HTTP routing and deployment

### 8.1 Restricted frontend routes

| Request | Expected behavior |
|---|---|
| GET `/` | Bootstrap and redirect |
| GET `/ui/` with valid cookie | Restricted shell |
| GET `/ui/` without valid cookie | 401 |
| GET `/ui/theme.css` with valid cookie | Allowed through gate |
| GET bundled `/ui/assets/...` | Allowed through gate |
| GET bundled `.woff2` under `/ui/static/fonts/` | Allowed through gate |
| POST Gradio queue/join | 403 |
| GET Gradio queue/data | 403 |
| POST Gradio run/call | 403 |
| Gradio upload route | 403 |
| Gradio private-file route | 403 |
| Unknown mounted route | 403 |
| Unsafe shell HTTP method | 403 |
| GET `/healthz` | 200 |

An allowed request may still receive a response from
Gradio indicating that the resource does not exist.

Allowing a request through the gate does not guarantee
the resource exists or is appropriate for public exposure.

### 8.2 Local development

Run:

```bash
FRONTEND_COOKIE_SECURE=false \
python -m uvicorn frontend.server:app \
  --host 127.0.0.1 \
  --port 7860 \
  --workers 1
```

Open:

`http://127.0.0.1:7860/`

Do not use `/ui/` as the initial URL in a fresh session.

The frontend intentionally disables Swagger documentation.

Backend Swagger documentation is separate and available
at `http://127.0.0.1:8000/docs` when the backend is running.

### 8.3 Production requirements

Production HTTPS deployment requires:

- Secure cookies.
- Trusted HTTPS termination.
- Correct proxy-header configuration.
- Explicit trusted hosts and origins.
- Request-origin and CSRF protection.
- Appropriate security headers.
- Request and upload size limits.
- Rate limiting where appropriate.
- Secret management.
- Redacted application logs.
- Session cleanup and expiration verification.
- No direct public exposure of legacy app.py.
- A single frontend worker under the current registry design.

Multi-worker or multi-replica deployment requires
a separately reviewed shared-session architecture.

The restricted frontend is not yet a production-ready
authenticated dashboard.

## 9. Testing strategy

### 9.1 Offline unit tests

Verify:

- Frontend HTTP client behavior.
- Credential management.
- Refresh synchronization.
- Session registry lifecycle.
- Anonymous browser creation.
- Identity rotation.
- Gradio ownership primitives.
- Cookie issuance and deletion.
- Error handling.

No database or Gemini is required.

### 9.2 HTTP security integration tests

File:

`tests/integration_tests/test_gradio_security.py`

Coverage includes:

- Anonymous cookie issuance.
- HttpOnly and SameSite attributes.
- Cookie reuse.
- Missing-cookie rejection.
- Forged-cookie rejection.
- Restricted shell accessibility.
- Theme stylesheet accessibility.
- Bundled font accessibility.
- Blocking of other static resources.
- Blocking of queue and event routes.
- Blocking of upload and file routes.
- Blocking of unknown paths.
- Blocking of unsafe methods.
- Independent browser cookie creation.
- Defensive asset-path validation.

These tests verify the restricted HTTP boundary.

They do not prove authorization of enabled interactive
Gradio operations.

### 9.3 Backend integration tests

Required for Phase 5.2.4:

- Registration.
- Login.
- Refresh rotation.
- Logout and revocation.
- Expired and invalid credentials.
- Protected endpoint authentication.
- Document ownership.

Use disposable accounts and isolated test storage.

### 9.4 Browser end-to-end tests

Required before enabling interactive functionality:

- Registration and login UI.
- Authentication persistence.
- Identity rotation.
- Logout.
- Browser isolation.
- Gradio session ownership.
- Queue-event ownership.
- Stream-result ownership.
- File and upload ownership.
- Session expiration.
- UI error recovery.

### 9.5 RAG and Gemini testing

Verify retrieval locally where possible.

Live Gemini testing requires explicit approval.

Record the model, cost/quota considerations,
requests, and results when such tests are authorized.

## 10. Implementation roadmap

### Phase 5.1 — Architecture

Initial architecture and API-contract review.

Status: Completed as a design milestone.

### Phase 5.2.1 — Frontend API client

Files:

- `frontend/api_client.py`
- `tests/unit_tests/test_frontend_api_client.py`

Status: Complete and unit-tested.

Historical checkpoint: 17 tests passed.

### Phase 5.2.2 — Credential manager

Files:

- `frontend/session_manager.py`
- `tests/unit_tests/test_frontend_session_manager.py`

Status: Complete and unit-tested.

Historical checkpoint: 15 tests passed.

### Phase 5.2.3A — Session registry

Files:

- `frontend/session_binding.py`
- `tests/unit_tests/test_frontend_session_binding.py`

Status: Complete and unit-tested.

### Phase 5.2.3B — Restricted HTTP security boundary

Files:

- `frontend/browser_session_binding.py`
- `frontend/http_session.py`
- `frontend/gradio_security.py`
- `frontend/server.py`
- `tests/unit_tests/test_browser_session_binding.py`
- `tests/unit_tests/test_http_session.py`
- `tests/integration_tests/test_gradio_security.py`

Status: COMPLETE for the restricted HTTP boundary.

Verified:

- Browser identity and cookie utilities.
- Anonymous cookie bootstrap.
- Missing/forged cookie rejection.
- Restricted ASGI frontend.
- Fail-closed Gradio route policy.
- Public stylesheet allowlist.
- Bundled font allowlist.
- Adversarial route-denial tests.
- Existing frontend regression.
- Complete project regression.
- Manual browser shell rendering.

Not included:

- Interactive login UI.
- Authorized Gradio event execution.
- Queue and stream resource ownership.
- Authenticated prediction/RAG callbacks.
- Production deployment certification.

### Phase 5.2.4 — Backend authentication integration

Status: Pending.

Verify actual FastAPI registration, login, refresh,
logout, and protected HTTP behavior through the
frontend API client.

### Phase 5.2.5 — Authentication UI

Status: Pending.

Implement:

- Registration.
- Login.
- Logout.
- Browser identity rotation.
- Credential-manager attachment.
- Authenticated callback integration.
- Request-origin and CSRF safeguards.

Do not enable interactive routes without the necessary
resource authorization.

### Phase 5.2.6 — Browser and session isolation

Status: Pending.

Verify adversarial cross-browser access to:

- Session hashes.
- Queue event identifiers.
- Streamed results.
- Uploaded files.
- Document identifiers.
- Expired and logged-out sessions.

### Phase 5.3 — Authenticated application workflows

Status: Planned.

Migrate direct-service callbacks to authenticated
FrontendAPIClient operations.

Implement authenticated:

- Insurance prediction.
- Advisory generation.
- Policy PDF upload.
- Document listing and deletion.
- Policy selection.
- Evidence-grounded RAG Q&A.
- Citation display.
- Error and expiration handling.

### Later phases

Phase 5.4–5.7:

Complete the remaining frontend integration,
end-to-end verification, issue review, and phase closure.

Phase 6:

Security, concurrency, reliability, recovery,
and operational verification.

Phase 7:

Expanded retrieval, answer-quality, citation,
abstention, and performance evaluation.

Phase 8:

CI/CD, staging, deployment, monitoring,
and release-readiness review.

## 11. Known risks and decisions

### R1 — Session-hash impersonation

Risk: A supplied session hash could be mistaken for
authentication or ownership.

Decision: Never trust session_hash alone.

Status: Interactive HTTP authorization pending.

### R2 — In-memory registry

Risk: Sessions are lost on restart and are not shared
between workers.

Decision: Single-process deployment initially.

Status: Accepted deployment restriction.

### R3 — Backend revocation

Risk: Local cleanup does not revoke backend sessions.

Decision: Explicit backend logout/revocation is required.

Status: Live integration pending.

### R4 — Refresh concurrency

Risk: Concurrent refresh attempts may conflict.

Decision: Per-session locking and consistent rotation.

Status: Unit-tested.

### R5 — External model costs

Risk: Gemini pricing, quotas, or model availability
may change.

Decision: Obtain approval before live model testing.

Status: No live Phase 5 model calls authorized.

### R6 — Browser-visible credentials

Risk: JWTs or registry handles could leak through UI state.

Decision: Keep credentials and handles server-side.

Status: Interactive UI verification pending.

### R7 — Gradio resource routes

Risk: Queue, event, upload, and file routes may bypass
callback-level checks.

Decision: Block them until ownership is verified.

Status: Restricted boundary verified; interactive
authorization pending.

### R8 — Cookie lifecycle mismatch

Risk: Browser cookie and server-side session expiration
may differ.

Decision: Verify coordinated expiration and cleanup.

Status: Full interactive lifecycle testing pending.

### R9 — Session fixation

Risk: An attacker may influence the browser identity
retained after authentication.

Decision: Rotate identity after successful login.

Status: Binding unit-tested; HTTP login integration pending.

### R10 — Deployment misconfiguration

Risk: Insecure cookies, untrusted proxy headers,
exposed legacy application, or multiple workers.

Decision: Explicit deployment restrictions.

Status: Production deployment review pending.

### R11 — Static-resource exposure

Risk: A broadly permitted static directory might
contain sensitive or user-controlled resources.

Decision: Narrow public resource allowlist and
review deployed static-file routing.

Status: Bundled font and route tests passed;
production asset review remains pending.

## 12. Verification record

### 12.1 Earlier frontend checkpoints

User-reported historical results:

- Browser session binding: 27 passed.
- HTTP cookie utilities: 7 passed.
- Frontend regression: 80 passed.
- Earlier full suite: 340 passed.
- Subsequent restricted HTTP suite: 13 passed.
- Subsequent full suite: 353 passed.
- Expanded HTTP suite: 35 passed.
- Expanded full suite: 375 passed.

These results are historical checkpoints.

### 12.2 Final Phase 5.2.3B verification

Date: 4 November 2026.

User-reported final results:

| Verification | Result |
|---|---|
| HTTP security integration | 37 passed |
| Complete project regression | 377 passed |
| Database integration tests | 35 skipped |
| Additional subtests | 12 passed |
| Restricted browser shell | Rendered successfully |
| Bundled Gradio font | HTTP 200 OK |
| Direct `/ui/` without valid cookie | HTTP 401 as designed |

The 35 database integration tests are disabled by default
through `RUN_PHASE4_DB_TESTS`.

They are intentionally skipped, not passed.

Run them only with an isolated test database and
isolated document/vector storage.

### 12.3 Final browser observations

A fresh private browser session successfully opened:

`http://127.0.0.1:7860/`

The browser displayed:

```text
Health Risk & Cost Advisor

Secure frontend initialization.
Authentication UI and protected operations
are not enabled yet.
```

This is the intended restricted Gradio shell.

The previously blocked resource:

`/ui/static/fonts/SourceSansPro/SourceSansPro-SemiBold.woff2`

returned HTTP 200 OK after the font allowlist correction.

Direct access to `/ui/` without a registered browser
cookie returned:

```json
{"detail": "Browser session required."}
```

That is the expected fail-closed response.

### 12.4 Verification commands

HTTP integration:

```bash
python -m pytest \
  tests/integration_tests/test_gradio_security.py -v
```

Frontend regression:

```bash
python -m pytest \
  tests/unit_tests/test_frontend_api_client.py \
  tests/unit_tests/test_frontend_session_manager.py \
  tests/unit_tests/test_frontend_session_binding.py \
  tests/unit_tests/test_browser_session_binding.py \
  tests/unit_tests/test_http_session.py -q
```

Complete regression:

```bash
python -m pytest -q -rs
```

No Gemini or other potentially paid external calls
are required for these tests.

## 13. Phase 5.2.3B closure decision

**Decision: COMPLETE — Restricted HTTP Security Boundary.**

Acceptance evidence:

- Browser cookie bootstrap verified.
- Missing and forged cookies rejected in HTTP tests.
- Restricted Gradio shell rendered in a browser.
- Required public stylesheet and font resources permitted.
- Protected Gradio event and file routes remain blocked.
- Unknown and unsafe routes fail closed.
- HTTP security integration: 37 passed.
- Complete regression: 377 passed.
- No reported test failures.
- Intentional database skips documented.

This decision applies only to the restricted,
non-interactive HTTP security boundary.

It does not certify:

- Interactive Gradio resource authorization.
- Authenticated dashboard functionality.
- Production HTTPS deployment.
- Complete security against all attack classes.
- End-to-end insurance prediction or RAG integration.

The next milestone is Phase 5.2.4.

## 14. Documentation and version control

At each milestone, record:

- Files created or modified.
- Architectural decisions.
- Security assumptions.
- Test commands and actual results.
- Known limitations.
- Regressions and fixes.
- Potentially chargeable external calls.

Maintain the engineering issue log throughout development.

Deliver the consolidated issue-log update at the
agreed phase-completion milestone.

Before committing:

1. Review the intended changed files.
2. Confirm no secrets or generated storage are staged.
3. Run `git diff --check`.
4. Confirm final test results.
5. Stage implementation, tests, README, and architecture.
6. Review the staged diff.
7. Commit the verified milestone.

Do not mark skipped tests as passed.

Do not mark disabled Gradio endpoints as successfully
authorized interactive endpoints.

Do not claim production readiness from local tests alone.