
# Phase 5 — Authenticated Frontend Architecture


**Updated:** 6 November 2026
**Document status:** Living architecture, engineering decisions, security findings and verification record
**Current milestone:** Phase 5.2.5B — Interactive authentication UI and HTTP security hardening locally verified
**Previous milestone:** Phase 5.2.4 — Backend-connected frontend authentication verified
**Next milestone:** Phase 5.2.6 — Authenticated Gradio event and resource ownership
**Deployment status:** Local development prototype; not production-ready

---

## 1. Purpose and scope

Phase 5 connects the existing Gradio application to the authenticated FastAPI backend while preserving the security guarantees established during Phase 4.

The intended application includes:

- User registration, login, refresh and logout.
- Insurance-cost prediction using the existing ML pipeline.
- Health-risk and insurance-cost advisory.
- Insurance-policy PDF upload and management.
- Authenticated single-policy and multi-policy RAG.
- Evidence-grounded answers with document and page references.
- Server-side credential and browser-session management.

The backend remains authoritative for authentication, session validity, document ownership and authorization.

**Phase 5.2.4 delivers a secured frontend HTTP authentication boundary, not a complete interactive authenticated Gradio dashboard.**

Development and testing prioritize free and local tools. Potentially chargeable services, including live Gemini requests, require explicit approval before use.

## 2. Architecture principles

1. Keep presentation, authentication coordination and backend business logic separate.
2. Keep JWT access tokens and refresh credentials on the Python server.
3. Give browsers only an opaque HttpOnly session-identity cookie.
4. Treat browser-provided identities and Gradio session hashes as untrusted.
5. Keep credential managers isolated between independent browser sessions.
6. Rotate browser identity after successful login.
7. Revoke the backend session when possible during logout or failed login handoff.
8. Clear local browser authentication even when backend logout fails.
9. Never report unconfirmed backend revocation as successful.
10. Validate the exact trusted Origin for authentication-changing requests.
11. Deny unapproved Gradio event, queue, upload and file routes.
12. Preserve the backend's independent JWT and PostgreSQL session checks.
13. Preserve existing document user/session ownership and expiration rules.
14. Use one frontend worker while session state remains in memory.
15. Do not equate local verification with production security certification.

## 3. Architecture and trust boundaries

```text
Browser
  |
  | Opaque HttpOnly browser identity cookie
  v
Frontend FastAPI ASGI Server
  |
  +-- Anonymous bootstrap
  +-- Trusted-Origin guard
  +-- Authentication HTTP routes
  +-- Fail-closed Gradio route gate
  +-- Restricted non-interactive Gradio shell
  |
  v
FrontendAuthenticationCoordinator
  |
  v
BrowserSessionBinding
  |
  v
Server-side session registry
  |
  v
SessionCredentialManager
  |
  v
FrontendAPIClient
  |
  | Backend HTTP requests
  | Credentials retained server-side
  v
FastAPI Backend
  |
  +-- Registration, login, refresh, logout
  +-- JWT validation
  +-- PostgreSQL active-session checks
  +-- Document user/session authorization
  +-- Insurance prediction and advisory
  +-- Policy PDF ingestion and management
  +-- Retrieval and RAG
         |
         +-- PostgreSQL
         +-- ChromaDB
         +-- Embedding and reranking models
         +-- Gemini, only with explicit approval
```

### 3.1 Browser boundary

The browser receives a session identity, not backend credentials. That identity is an opaque lookup value and must be validated against server-side state.

### 3.2 Frontend boundary

The frontend coordinates login, credential storage, refresh, logout and browser identity rotation. It does not independently grant document authorization.

### 3.3 Backend boundary

The backend verifies JWT claims and the associated active PostgreSQL session. Protected document operations additionally enforce user/session ownership and document expiration.

## 4. Component responsibilities

### 4.1 `frontend/api_client.py`

Provides backend HTTP authentication transport.

Responsibilities:

- Send login, refresh and logout requests.
- Preserve backend HTTP error classification.
- Handle connection failures and timeouts.
- Keep credentials out of browser responses.
- Avoid a globally shared mutable authenticated identity.

### 4.2 `frontend/session_manager.py`

Maintains credentials for one authenticated frontend session.

Responsibilities:

- Retain access and refresh credentials server-side.
- Supply access tokens for backend requests.
- Refresh credentials when required.
- Coordinate refresh safely.
- Clear invalid credentials.
- Request backend logout.

The manager does not determine document ownership.

### 4.3 `frontend/session_binding.py`

Provides server-side session registry and ownership support.

The current registry is process-local and in memory.

Consequences:

- The secured frontend requires one worker.
- Restarting the frontend loses its local session bindings.
- Multi-worker deployment requires a reviewed shared-session design.

### 4.4 `frontend/browser_session_binding.py`

Associates opaque browser identities with server-side session managers.

Responsibilities:

- Create anonymous browser identities.
- Resolve registered browser identities.
- Bind authenticated managers.
- Rotate identities after login.
- Terminate browser bindings.
- Prevent one browser from resolving another browser's credentials.

### 4.5 `frontend/http_session.py`

Handles browser session cookies.

Security requirements:

- HttpOnly cookie.
- SameSite=Strict.
- Secure cookie in HTTPS environments.
- Validated registered browser identity.
- Correct cookie deletion on logout.
- Configured session lifetime.

`FRONTEND_COOKIE_SECURE=false` is restricted to local HTTP development.

### 4.6 `frontend/gradio_security.py`

Implements the mounted Gradio HTTP security gate.

The gate permits the restricted shell and narrowly approved public resources. It denies unapproved:

- Event execution.
- Queue operations.
- Upload operations.
- File-serving routes.
- Reset operations.
- Static resources not explicitly permitted.

The gate must remain fail-closed until resource ownership checks exist.

A Gradio `session_hash` is not an authentication credential.

### 4.7 `frontend/auth_coordinator.py`

Introduced in Phase 5.2.4.

Coordinates:

- Backend login.
- Server-side credential-manager creation.
- Browser identity rotation.
- Rollback when login handoff fails.
- Backend revocation attempts during rollback.
- Authenticated-state lookup.
- Access-token retrieval.
- Logout and local session termination.

Concurrent-login tests cover winning and losing browser bindings, including revocation of the losing backend session.

### 4.8 `frontend/auth_origin.py`

Introduced in Phase 5.2.4.

Enforces exact trusted-Origin validation on authentication-changing frontend HTTP requests.

Requirements:

- Explicitly configured trusted frontend origin.
- Rejection of missing or malformed origins.
- Rejection of foreign origins.
- No trust derived from unvalidated request headers.

Local configuration:

```bash
FRONTEND_ALLOWED_ORIGIN=http://127.0.0.1:7860
```

Origin validation protects the current authentication HTTP routes. Future interactive Gradio operations require their own complete authorization and CSRF review.

### 4.9 `frontend/server.py`

Hosts the secured frontend ASGI application.

Implemented responsibilities:

- Anonymous browser bootstrap.
- Restricted Gradio shell mounting.
- Authentication status.
- Backend-connected login.
- Backend-connected logout.
- Origin enforcement.
- Browser cookie issuance, rotation and deletion.
- Fail-closed Gradio route restrictions.

Current HTTP routes:

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/` | Anonymous bootstrap and redirect |
| GET | `/healthz` | Frontend health |
| GET | `/frontend-auth/status` | Non-sensitive authentication status |
| POST | `/frontend-auth/login` | Backend login and browser identity rotation |
| POST | `/frontend-auth/logout` | Backend logout attempt and local cleanup |
| GET | `/ui/` | Restricted non-interactive Gradio shell |

Login failure handling includes:

- HTTP 401 for rejected credentials.
- HTTP 403 for rejected request origins.
- HTTP 409 for an already authenticated browser.
- HTTP 503 for unavailable backend authentication.

Sensitive credentials must not appear in browser responses.

### 4.10 Legacy `app.py`

The original Gradio application remains separate from the secured frontend entry point.

Its existing prediction/advisory workflows must not bypass the new authorization boundary when integrated later.

### 4.11 FastAPI backend

Existing backend responsibilities remain unchanged:

- Registration and password hashing.
- JWT issuance and validation.
- Refresh-token rotation.
- Session revocation.
- PostgreSQL session persistence.
- Protected policy-document endpoints.
- Temporary document expiration and cleanup.
- ML prediction, advisory and RAG services.

## 5. Security enforcement layers

### Layer 1 — Browser HTTP security

**Status: Implemented and locally verified.**

Includes:

- Opaque browser cookie.
- Anonymous session bootstrap.
- Server-side identity binding.
- Identity rotation after login.
- Trusted-Origin checks.
- Local logout cleanup.
- Restricted Gradio route allowlist.

### Layer 2 — Gradio event and resource ownership

**Status: Pending Phases 5.2.5–5.2.6.**

Required work:

- Gradio session ownership.
- Queue/event request ownership.
- Callback authorization.
- File and upload authorization.
- Cross-browser isolation.
- Session-hash impersonation resistance.
- Authorization before protected event execution.

Current Gradio event routes remain blocked.

### Layer 3 — Backend authorization

**Status: Implemented in Phase 4 and retained.**

Includes:

- JWT signature and claim validation.
- PostgreSQL-backed active-session verification.
- Refresh-token rotation and revocation.
- User/session document ownership.
- Temporary document expiration.
- Backend-enforced authorization independent of frontend state.

## 6. Authentication lifecycle

### 6.1 Anonymous bootstrap

1. Browser requests `/`.
2. Frontend resolves or creates an anonymous browser identity.
3. Frontend issues an opaque HttpOnly cookie.
4. Browser receives an HTTP 303 redirect to `/ui/`.
5. Restricted Gradio shell renders.
6. Authentication status is `false`.

### 6.2 Registration

Backend registration exists.

Interactive frontend registration is pending Phase 5.2.5.

### 6.3 Login

1. Browser sends its registered anonymous cookie.
2. Frontend validates the request Origin.
3. Frontend forwards credentials to the backend.
4. Backend authenticates and creates a PostgreSQL-backed session.
5. Frontend credential manager retains backend credentials.
6. Browser identity rotates.
7. Frontend issues a replacement opaque cookie.
8. Authentication status becomes `true`.

Backend access and refresh tokens are not returned to the browser.

### 6.4 Protected backend requests

The future authenticated application workflow is:

1. Browser sends its opaque cookie.
2. Frontend resolves its server-side credential manager.
3. Credential manager supplies or refreshes an access token.
4. Frontend API client calls the backend.
5. Backend validates JWT, session and resource ownership.
6. Frontend displays only authorized results.

Interactive Gradio callbacks are not enabled in Phase 5.2.4.

### 6.5 Access-token refresh

**Status: Implemented and live verified.**

The frontend credential manager requests a new access token through the real FastAPI backend.

The backend rotates the refresh credential.

The Phase 5.2.4 live smoke test verified:

- Real backend login.
- Real backend refresh completion.
- Returned access token.
- Refresh-token rotation.
- Continued authenticated frontend status.
- Backend logout after refresh.
- Browser-session invalidation.

**Result: 7/7 checks passed.**

#### JWT equality finding

The first refresh smoke-test run failed on an assertion requiring:

```python
refreshed_access != original_access
```

Inspection of `services/token_service.py` established that the access JWT contains:

- `sub`
- `sid`
- `iat`
- `exp`
- `iss`
- `token_type`

The JWT does not contain a unique `jti` claim.

JWT time claims are encoded at whole-second precision. Login and refresh within the same second can therefore produce byte-identical access JWTs.

This is not evidence that refresh failed.

The smoke test was corrected to require a returned access token and separately verify refresh-token rotation.

**Decision:** Do not modify the backend JWT contract merely to satisfy an unsupported access-token uniqueness assertion.

### 6.6 Logout

1. Browser sends its registered identity cookie.
2. Frontend validates the request Origin.
3. Coordinator attempts backend logout.
4. Frontend terminates the local browser binding.
5. Frontend clears the browser cookie.
6. Authentication status becomes `false`.

Backend revocation uncertainty must not be reported as confirmed success.

### 6.7 Expiration

Frontend browser-session expiration and backend policy-document inactivity expiration are separate mechanisms.

The backend independently enforces session validity and document ownership.

## 7. Gradio security findings

### 7.1 Restricted shell

The secured Gradio shell renders without enabling authenticated application workflows.

The shell's initialization placeholder is expected until the interactive UI is implemented.

### 7.2 Static JavaScript HTTP 403

The browser requested:

```text
/ui/static/js/iframeResizer.contentWindow.min.js
```

The security gate returned HTTP 403.

The shell continued to render.

The dedicated Gradio security smoke test subsequently verified this denial alongside denial of queue, upload, file and event routes.

**Decision:** Accept this as a fail-closed restriction for the current non-interactive milestone.

Do not broadly allowlist `/ui/static/`.

Reassess the specific resource only if a later authorized UI workflow requires it, with a narrow allowlist and regression test.

### 7.3 Verified restricted-route checks

**Result: 7/7 passed.**

Checks included:

- Anonymous bootstrap.
- Restricted shell access.
- Static JavaScript denial.
- Queue denial.
- Upload denial.
- File-serving denial.
- Event-execution denial.

These checks establish the tested restrictions, not comprehensive Gradio callback security.

## 8. Local development

### 8.1 Backend

Run in Terminal 1:

```bash
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Expected:

- FastAPI starts on port 8000.
- `/health` returns `{"status":"ok"}`.
- Swagger is available at `http://127.0.0.1:8000/docs`.

The backend root `/` is not defined; HTTP 404 there is expected.

### 8.2 Secured frontend

Run in Terminal 2:

```bash
export API_BASE_URL=http://127.0.0.1:8000
export FRONTEND_ALLOWED_ORIGIN=http://127.0.0.1:7860
export FRONTEND_COOKIE_SECURE=false

python -m uvicorn frontend.server:app --host 127.0.0.1 --port 7860
```

Expected:

- Frontend starts on port 7860.
- Opening `http://127.0.0.1:7860/` bootstraps a browser identity.
- Browser redirects to `/ui/`.
- Restricted shell renders.

Use the root URL for initial navigation, not direct `/ui/` access without a cookie.

### 8.3 Environment boundaries

- Local HTTP only for insecure development cookies.
- Single frontend worker.
- In-memory frontend sessions.
- Synthetic insurance documents.
- Disposable authentication accounts.
- Isolated PostgreSQL test database for destructive integration tests.
- No paid Gemini calls without approval.

## 9. Testing and verification

### 9.1 Offline unit tests

Coverage includes:

- Frontend API client.
- Credential manager.
- Session registry and binding.
- Browser identity rotation.
- Authentication coordinator.
- Login rollback.
- Concurrent login.
- Origin validation.
- Logout failure classification.

### 9.2 HTTP integration tests

Coverage includes:

- Anonymous bootstrap.
- Cookie issuance and rotation.
- Login success and failure.
- Browser isolation.
- Token confidentiality.
- Origin rejection.
- Logout and backend failures.
- Cookie invalidation.
- Restricted Gradio routes.

### 9.3 PostgreSQL integration tests

The guarded test database is:

```text
health_rag_migration_test
```

The database-enabled regression command is:

```bash
RUN_PHASE4_DB_TESTS=1 python -m pytest -q
```

Do not disable the test-database guard or point destructive tests at the working application database.

### 9.4 Live authentication smoke test

Script:

```text
scripts/smoke_tests/verify_frontend_auth.py
```

Result:

**8/8 passed.**

Verified:

- Anonymous bootstrap.
- Independent browser identities.
- Real frontend-to-backend login.
- Browser identity rotation.
- Browser B remains unauthenticated.
- Real backend logout.
- Cookie invalidation.
- Browser isolation after logout.

### 9.5 Live refresh smoke test

Script:

```text
scripts/smoke_tests/verify_frontend_refresh.py
```

Run from the repository root as a module:

```bash
python -m scripts.smoke_tests.verify_frontend_refresh
```

Result:

**7/7 passed.**

The script uses a disposable account and the running local backend.

It is a manual smoke test, not an automatically collected pytest test.

### 9.6 Gradio security smoke test

Script:

```text
scripts/smoke_tests/verify_gradio_security.py
```

Result:

**7/7 passed.**

The expected HTTP 403 responses confirm that unapproved Gradio routes remain blocked.

### 9.7 Full regression

Final reported command:

```bash
RUN_PHASE4_DB_TESTS=1 python -m pytest -q
```

Final result on 5 November 2026:

```text
470 passed, 12 subtests passed in 15.42s
```

Additional checks:

- Refresh smoke-test Python compilation: passed.
- `git diff --check`: passed.
- Pytest exit code: 0.
- Git whitespace-check exit code: 0.

No regression failure was reported.

### 9.8 Verification interpretation

The tests establish the behavior of the covered local implementation.

They do not establish:

- Production security certification.
- Multi-worker correctness.
- Complete concurrency/load resilience.
- Interactive Gradio callback authorization.
- RAG answer accuracy or citation faithfulness.
- Public deployment readiness.

No live Gemini requests were required for the Phase 5.2.4 verification.

## 10. Phase 5 implementation roadmap

### 5.1 — Architecture and API review

**Complete.**

Reviewed the frontend/backend boundary and selected backend HTTP authentication with server-side credential ownership.

### 5.2.1 — Frontend API client

**Complete.**

Implemented backend HTTP authentication transport.

### 5.2.2 — Credential manager

**Complete.**

Implemented server-side access/refresh credential lifecycle.

### 5.2.3A — Session registry and binding

**Complete.**

Implemented server-side ownership and browser-binding foundations.

### 5.2.3B — Restricted frontend HTTP boundary

**Complete — 4 November 2026.**

Implemented anonymous bootstrap, opaque browser cookie, restricted Gradio shell and fail-closed route gate.

Historical verification:

- 37 HTTP security integration tests passed.
- 80 frontend regression tests passed.
- Full suite: 377 passed, 35 skipped, 12 subtests passed.

These are historical checkpoints, not the current full-suite totals.

### 5.2.4 — Backend-connected frontend authentication

**Implementation and technical verification complete — 5 November 2026.**

Delivered:

- Authentication coordinator.
- Trusted-Origin guard.
- Backend-connected HTTP login.
- Non-sensitive authentication status.
- Backend-connected HTTP logout.
- Server-side credential ownership.
- Browser identity rotation.
- Login rollback and concurrency handling.
- Backend error classification.
- Local logout cleanup.
- Live authentication smoke test.
- Live refresh smoke test.
- Restricted Gradio security verification.

Verification:

| Check | Result |
| --- | --- |
| Focused coordinator/security tests | 45 passed |
| Existing frontend security tests | 44 passed |
| Logout/error tests | 13 passed |
| Combined frontend HTTP tests | 23 passed |
| Guarded PostgreSQL authentication contract | 22 passed |
| Live authentication smoke | 8/8 passed |
| Restricted Gradio security smoke | 7/7 passed |
| Live refresh smoke | 7/7 passed |
| Database-enabled full regression | 470 passed, 12 subtests passed |
| Syntax and Git whitespace | Passed |

**Remaining administrative work:** Update the engineering issue log, review documentation, inspect Git changes, stage scoped files and commit.


### 5.2.5 — Interactive authentication UI

**Status:** Phase 5.2.5B implemented and locally verified — 6 November 2026.

Delivered:

- Dedicated `/auth` registration and login page.
- Backend-connected registration.
- Browser-facing authentication status and logout.
- Safe authentication error handling.
- Content Security Policy and HTTP security headers.
- Bounded authentication request bodies.
- Gradio redirect regression correction.
- Dedicated authentication HTTP security tests.

Verification:

- 28 new authentication security tests passed.
- 38 existing Gradio security tests passed.
- 464 full-suite tests passed.
- 35 skipped.
- 12 subtests passed.

Protected Gradio callbacks, queues, uploads and file operations remain disabled.

**Next:** Phase 5.2.6 — Gradio event/resource ownership.

### 5.2.6 — Gradio event/resource ownership

**Pending.**

Planned:

- Callback authorization.
- Queue ownership.
- Event ownership.
- Upload and file authorization.
- Cross-browser adversarial testing.
- Session-hash impersonation resistance.

### 5.3 — Authenticated application workflows

**Pending.**

Integrate:

- Insurance-cost prediction.
- Health-risk and cost advisory.
- Insurance-policy upload and management.
- Policy selection and retrieval.
- Evidence-grounded single/multi-policy Q&A.
- Document expiration and error states.

### Later phases

- **Phase 6:** End-to-end security, concurrency, reliability and recovery.
- **Phase 7:** Expanded retrieval, answer and citation evaluation.
- **Phase 8:** CI/CD, deployment, monitoring and release review.

## 11. Risk register

| Risk | Decision | Status |
| --- | --- | --- |
| Gradio session-hash impersonation | Require server-side ownership | Interactive enforcement pending |
| In-memory session registry | One local frontend worker | Shared storage needed before scaling |
| Backend logout failure | Clear local access; report uncertainty | Tested |
| Refresh concurrency | Coordinate refresh and preserve rotation | Unit coverage and live refresh verified |
| Browser-visible JWT leakage | Keep credentials server-side | HTTP confidentiality tested |
| Gradio event/queue/file exposure | Deny until authorized | Restricted routes verified |
| Cookie/session expiration mismatch | Fail closed and clear invalid state | Further lifecycle UX pending |
| Session fixation | Rotate identity on login | Verified |
| Misconfigured cookies/Origin/proxy | Explicit configuration and deployment review | Local configuration verified |
| Static-resource exposure | Narrow allowlists only | Fail-closed iframe-resizer 403 accepted |
| Login abuse | Add rate limiting before public deployment | Deferred |
| Paid model calls | Require explicit approval | No Gemini calls needed for this phase |
| Public security and privacy | Separate predeployment review | Pending |

## 12. Engineering findings

### Finding A — Python smoke-test import path

Initial direct execution:

```bash
python scripts/smoke_tests/verify_frontend_refresh.py
```

failed to import the top-level `frontend` package.

Running the script from the project root using:

```bash
python -m scripts.smoke_tests.verify_frontend_refresh
```

resolved the import-path issue.

Classification: Local test invocation issue, not an application authentication defect.

### Finding B — Access JWT equality assertion

The first live refresh smoke test completed login and backend refresh, then failed because it required a different access JWT string.

Root cause: The backend JWT contract does not guarantee a unique token string for two issuances within the same second.

Resolution: Corrected the smoke-test assertion; retained verification of refresh-token rotation.

Classification: Test assumption defect, not demonstrated backend refresh failure.

### Finding C — Gradio iframe-resizer HTTP 403

The restricted shell requested a static JavaScript asset that the fail-closed gate denied.

The shell still rendered and all seven Gradio security smoke checks passed.

Resolution: Preserve the denial for the current non-interactive phase.

Classification: Expected security restriction; reconsider narrowly if future UI behavior requires the resource.

### Finding D — Disposable account HTTP 401

One previously used test account was rejected during earlier live authentication testing. Another disposable account successfully authenticated and completed the full smoke test.

The rejected account's credentials/history were not investigated.

Classification: Unresolved account-specific observation; not sufficient evidence of a general application defect.

## 13. Phase 5.2.4 acceptance decision

**Decision: Technical implementation and verification COMPLETE.**

Evidence:

1. Backend-connected frontend login/logout verified.
2. Server-side credential ownership retained.
3. Browser identity rotation verified.
4. Independent browser isolation verified.
5. Trusted-Origin enforcement covered.
6. Backend failure classification covered.
7. PostgreSQL authentication contract passed.
8. Real refresh-token rotation verified.
9. Restricted Gradio routes remained blocked.
10. Full guarded regression passed with no failures.
11. Syntax and Git whitespace checks passed.

This acceptance is limited to the secured frontend HTTP authentication boundary.

It does not authorize interactive Gradio events, file access, production deployment or real customer-data processing.

**Administrative closure remains pending until the issue log and scoped Git commit are completed.**

## 14. Documentation and version-control closure

Before staging:

1. Replace the root README with the verified Phase 5.2.4 version.
2. Replace this architecture document.
3. Reconcile the existing engineering issue log.
4. Review the exact changed and untracked files.
5. Confirm no secrets, local captures or unrelated research files are included.
6. Run the pre-staging checks.
7. Stage only Phase 5.2.4 source, tests, smoke scripts and approved documentation.
8. Inspect the staged diff.
9. Create one descriptive, scoped commit.

Exclude unless separately approved:

```text
docs/research/
tests/evaluation/phase447c_performance.local.json
tests/evaluation/phase447c_retrieval_results.local.json
```

The commit message should describe the actual security and authentication work, not merely state that Phase 5.2.4 was completed.

No Phase 5.2.4 commit is recorded at the time of this document update.

---

**Next action:** Complete the engineering issue-log reconciliation and pre-staging review. After a clean staged-diff inspection, commit the verified Phase 5.2.4 implementation. Phase 5.2.5 is the next development milestone.



---

# Phase 5.2.5B — Interactive Authentication UI and HTTP Security Hardening

**Verification date:** 6 November 2026
**Status:** Local implementation and automated regression verification complete
**Scope:** Browser-facing registration/login interface, authentication HTTP routes, browser security headers, request-body limits, and Gradio security regression.

## 1. Objective

Extend the existing Phase 5.2.4 backend-connected authentication boundary with a usable browser authentication interface.

The implementation must preserve:

- Server-side ownership of JWT and refresh credentials.
- Independent browser-session identities.
- Backend-controlled authentication and authorization.
- Trusted-Origin validation.
- Browser identity rotation after login.
- Safe logout and error handling.
- Fail-closed Gradio routes.
- Existing Phase 4 document ownership and lifecycle rules.

The implementation does not enable protected Gradio callbacks, insurance-policy uploads or RAG operations.

## 2. Architecture

```text
Browser
  |
  | GET /
  v
Frontend FastAPI
  |
  | Create or reuse anonymous identity
  | Set opaque HttpOnly cookie
  | HTTP 303
  v
/auth
  |
  | Registration / Login interface
  | CSP nonce and security headers
  |
  | Same-origin HTTP requests
  v
/frontend-auth/*
  |
  +-- ASGI request-body limiter (4096 bytes)
  +-- Trusted-Origin validation
  +-- Browser identity validation
  |
  v
FrontendAuthenticationCoordinator
  |
  +-- BrowserSessionBinding
  +-- Per-session credential manager
  |
  v
FrontendAPIClient
  |
  | Backend HTTP authentication
  v
FastAPI Backend
  |
  +-- Argon2id password verification
  +-- JWT issuance and validation
  +-- PostgreSQL session persistence
  +-- Refresh-token rotation
  +-- Logout and revocation
```

The browser does not receive backend JWT or refresh credentials.

## 3. Component responsibilities

### 3.1 frontend/auth_page.py

Provides the interactive authentication HTML.

Responsibilities:

- Render registration and login forms.
- Submit credentials to same-origin frontend routes.
- Display safe authentication errors.
- Query non-sensitive authentication status.
- Support logout.
- Use a per-response Content Security Policy script nonce.

Security decision:

Authentication credentials are submitted to the frontend server. Backend tokens are never placed in browser JavaScript state, localStorage or Gradio state.

### 3.2 frontend/server.py

Provides the secured frontend ASGI entry point.

Current HTTP routes:

| Method | Route | Responsibility |
| --- | --- | --- |
| GET | / | Anonymous browser bootstrap and redirect |
| GET | /auth | Interactive authentication page |
| GET | /healthz | Frontend health |
| GET | /frontend-auth/status | Non-sensitive authentication status |
| POST | /frontend-auth/register | Backend account registration |
| POST | /frontend-auth/login | Login and browser identity rotation |
| POST | /frontend-auth/logout | Logout and local browser access cleanup |
| GET | /ui/ | Restricted non-interactive Gradio shell |

The root redirect is now:

GET / -> HTTP 303 -> /auth

The previous redirect to /ui/ was valid for the earlier restricted-shell milestone but is superseded.

### 3.3 AuthenticationBodyLimitMiddleware

Purpose:

Enforce an authentication request-body limit before the FastAPI endpoint parses or processes the request.

Maximum body size:

4096 bytes.

Protected routes:

- POST /frontend-auth/register
- POST /frontend-auth/login
- POST /frontend-auth/logout

Implementation:

- Intercepts authentication POST requests using the ASGI interface.
- Reads the incoming body with a bounded byte count.
- Rejects requests exceeding the configured limit.
- Returns HTTP 413 for oversized bodies.
- Replays accepted bodies through the ASGI receive interface.
- Avoids private Starlette request attributes.

Design rationale:

A security-sensitive request-size limit should not depend on undocumented framework internals.

### 3.4 Existing authentication components

The following responsibilities remain unchanged:

- frontend/api_client.py: Backend HTTP transport.
- frontend/session_manager.py: Per-session server-side credential lifecycle.
- frontend/session_binding.py: In-memory session registry.
- frontend/browser_session_binding.py: Opaque browser identity binding.
- frontend/http_session.py: Browser cookie issuance and deletion.
- frontend/auth_coordinator.py: Login, identity rotation, rollback and logout coordination.
- frontend/auth_origin.py: Exact trusted-Origin validation.
- frontend/gradio_security.py: Fail-closed Gradio HTTP route restrictions.

The backend remains authoritative for JWT validation, PostgreSQL session validity and policy-document ownership.

## 4. Authentication behavior

### Registration

1. Browser loads /auth.
2. User submits registration details.
3. Frontend validates the request boundary.
4. Frontend forwards registration to the backend.
5. Backend performs account creation and password hashing.
6. Successful registration returns HTTP 201.
7. The browser remains unauthenticated until login.

Duplicate registration returns a safe HTTP 409 response.

### Login

1. Browser submits credentials through the frontend.
2. Origin and browser identity are validated.
3. Frontend coordinator requests backend authentication.
4. Backend validates credentials and creates a persistent session.
5. Server-side credential state is associated with the browser session.
6. Browser identity is rotated.
7. Frontend returns HTTP 200 and a replacement opaque cookie.

Backend tokens remain server-side.

### Logout

1. Browser submits a logout request.
2. Frontend validates Origin and browser identity.
3. Coordinator attempts backend logout and revocation.
4. Local browser access is cleared.
5. Browser identity cookie is removed.
6. Authentication status becomes false.

Unconfirmed backend revocation must not be reported as confirmed success.

## 5. Engineering issue P5.2.5B-01

### Title

Legacy Gradio bootstrap redirect assertion.

### Observed failure

The existing Gradio security integration suite reported 28 failures.

All 28 failures stopped at the browser bootstrap assertion before executing their intended protected-route checks.

### Root cause

The test helper expected:

```python
assert response.headers["location"] == "/ui/"
```

The new authentication architecture intentionally redirects to:

```python
assert response.headers["location"] == "/auth"
```

### Correction

Updated:

tests/integration_tests/test_gradio_security.py

Changes:

1. Updated bootstrap_browser() to expect /auth.
2. Added test_root_redirects_to_authentication_page().
3. Preserved the existing protected Gradio route assertions.
4. Preserved forged-cookie and missing-cookie checks.
5. Preserved unsafe-method and unknown-route checks.
6. Preserved browser identity isolation tests.

### Expected result

38 Gradio security tests pass.

### Observed result

38 passed.

### Classification

Resolved test compatibility regression.

The original failures did not establish an authorization vulnerability because the tests stopped before reaching their security assertions.

### Engineering lesson

When an application entry point changes, integration tests must be updated to reflect the new contract without weakening security expectations.

## 6. Engineering issue P5.2.5B-02

### Title

Private Starlette request-body attribute dependency.

### Observed implementation

The previous request-body handling used:

```python
request._body = bytes(body)
```

### Root cause

The middleware consumed an HTTP request body and depended on a private Starlette attribute to make it available downstream.

### Engineering risk

Private framework attributes are not guaranteed stable interfaces.

This creates avoidable maintenance and compatibility risk.

### Correction

Replaced the private attribute approach with pure ASGI request-body handling.

The middleware:

- Enforces a 4096-byte limit.
- Returns HTTP 413 for oversized requests.
- Replays accepted request bodies using ASGI receive.
- Preserves normal downstream request validation.
- Prevents oversized requests from reaching authentication handlers.

### Verification

The new authentication security tests passed.

The full default regression suite passed.

### Classification

Framework compatibility and HTTP security hardening.

### Status

Implemented and covered by passing local tests.

## 7. New automated security verification

New test file:

tests/integration_tests/test_phase525b_auth_security.py

The test suite covers:

- Authentication-page security headers.
- Content Security Policy nonce uniqueness.
- HttpOnly browser identity cookies.
- SameSite cookie restrictions.
- Successful registration.
- Registration without a valid browser identity.
- Missing and untrusted Origin rejection.
- Oversized request rejection.
- Accepted request-body handling.
- Malformed JSON rejection.
- Invalid registration fields.
- Duplicate registration error mapping.
- Backend registration failure handling.
- Invalid login handling.
- Browser identity rotation.
- Browser-facing JWT non-disclosure.
- Logout cookie invalidation.
- Logout backend failure handling.
- Independent browser identities.
- Continued Gradio route restrictions.

Backend authentication operations are mocked for this suite.

These tests do not make paid API requests or independently prove backend JWT cryptography.

## 8. Verification results

### Focused authentication security suite

Command:

```bash
python -m pytest tests/integration_tests/test_phase525b_auth_security.py -q --tb=short
```

Observed:

28 passed.

### Existing Gradio security suite

Command:

```bash
python -m pytest tests/integration_tests/test_gradio_security.py -q --tb=short
```

Observed:

38 passed.

### Full default regression suite

Command:

```bash
python -m pytest tests/ -q --tb=short
```

Observed:

464 passed, 35 skipped, 12 subtests passed.

### Interpretation

The previous default-suite checkpoint was 436 passed.

The addition of 28 authentication security tests increased the passing count to 464.

The 35 skipped tests are not counted as successful tests.

The earlier Phase 5.2.4 guarded database-enabled regression result of 470 passed belongs to a different test configuration and remains a separate historical checkpoint.

No regression failures were reported.

## 9. Manual browser verification

The following behavior was reported during interactive testing:

| Scenario | Observed behavior |
| --- | --- |
| New account registration | HTTP 201 |
| Duplicate account registration | HTTP 409 |
| Valid login | HTTP 200 |
| Logout | HTTP 200 |
| Refresh after logout | Sign-in state displayed |
| Separate browser contexts | Logout isolation observed |
| Browser Back navigation | Disabled during the tested flow |

Browser history behavior is not an authorization control.

Security depends on server-side session validation and route authorization.

## 10. Security limitations

Phase 5.2.5B does not establish:

- Production security certification.
- Authenticated Gradio callback authorization.
- Queue/event ownership.
- Protected upload and file-serving authorization.
- Multi-worker session correctness.
- Full concurrent-load resilience.
- Rate limiting or public-deployment abuse protection.
- RAG answer correctness.
- Complete insurance-policy workflow integration.

The frontend registry remains in-memory and single-worker.

FRONTEND_COOKIE_SECURE=false is restricted to local HTTP development.

No real customer documents should be used in an unreviewed deployment.

## 11. Architecture decision record

### ADR-5.2.5B-01: Dedicated authentication page

Decision:

Serve registration/login at /auth before enabling protected Gradio operations.

Reason:

Separate the browser authentication boundary from future authenticated application callbacks.

### ADR-5.2.5B-02: Server-side credential ownership

Decision:

Continue storing backend credentials in per-session Python credential managers.

Reason:

Avoid exposing JWT and refresh credentials to browser-side state.

### ADR-5.2.5B-03: Pure ASGI body-size enforcement

Decision:

Use the ASGI receive interface rather than private Starlette request attributes.

Reason:

Improve framework compatibility, testability and request-boundary control.

### ADR-5.2.5B-04: Preserve fail-closed Gradio routes

Decision:

Do not enable event, queue, upload or file routes during authentication UI development.

Reason:

Browser identity alone does not establish ownership of Gradio events or private resources.

## 12. Interview preparation — engineering rationale

**Q: Why use JWT plus database-backed sessions?**

JWTs support signed access claims, while the database enables explicit session revocation and active-session validation.

A cryptographically valid JWT is insufficient if its associated database session has expired or been revoked.

**Q: Why rotate browser identity after login?**

Rotation reduces session-fixation risk by replacing the pre-authentication browser identity when authenticated credentials become associated with a session.

**Q: Why keep JWTs server-side?**

It reduces browser-side credential exposure and separates frontend presentation from backend authentication transport.

**Q: Why enforce an authentication body-size limit?**

It rejects oversized requests before expensive or sensitive authentication processing and establishes a bounded HTTP input contract.

**Q: Why avoid request._body?**

It is a private implementation attribute. The ASGI receive interface is the supported request-message boundary.

**Q: Why do 38 passing Gradio tests not mean the interactive dashboard is secure?**

Those tests verify the restricted HTTP boundary. They do not prove authorization for enabled callbacks, queued events, uploaded files or session-hash ownership.

**Q: Why is the current frontend limited to one worker?**

The browser/session registry is process-local. Independent workers would not automatically share identity bindings or credential state.

Shared session storage and cross-worker coordination must be designed before horizontal scaling.

**Q: What happens if a user attempts to access another user's insurance policy?**

The backend must validate the authenticated user, active database session, document ownership and document expiration. Frontend authentication alone does not grant document access.

**Q: What remains before deployment?**

Authenticated Gradio event ownership, resource authorization, rate limiting, privacy review, concurrency testing, operational monitoring, recovery procedures and deployment security configuration.

## 13. Phase acceptance

Phase 5.2.5B meets its defined local implementation and automated regression acceptance criteria based on the user-reported test results.

This acceptance is limited to the interactive authentication HTTP boundary and restricted Gradio shell.

It does not approve production deployment or protected interactive application workflows.

## 14. Next engineering milestone

Phase 5.2.6 — Authenticated Gradio Event and Resource Ownership.

Planned engineering tasks:

1. Review the supported Gradio 6.30.0 session and request interfaces.
2. Bind Gradio sessions to authenticated server-side browser identities.
3. Authorize event execution before protected callbacks run.
4. Validate queue and event ownership.
5. Implement controlled upload and file access.
6. Reject cross-browser and cross-session impersonation.
7. Preserve backend document user/session authorization.
8. Add negative and adversarial security tests.
9. Run complete local regression verification.
10. Record decisions, failures, corrections and measured results.

Do not enable protected Gradio workflows until the corresponding ownership checks pass.