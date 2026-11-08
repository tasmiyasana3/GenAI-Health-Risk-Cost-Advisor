
# Phase 5 — Authenticated Frontend Architecture and Engineering Record

**Project:** GenAI Health Risk & Cost Advisor V3  
**Branch:** `version_3`  
**Last updated:** 8 November 2026
**Frontend:** FastAPI with mounted Gradio 6.30.0  
**Backend:** FastAPI, PostgreSQL-backed authentication and document ownership  
**Latest confirmed source commit before Phase 5.2.6C staging:** `4818f23` — `feat(auth): complete Phase 5.2.6B trusted Gradio sessions` (documentation commit: `aca267b`)
**Current milestone:** Phase 5.2.6C FastAPI-controlled secure execution boundary implemented and locally tested; native Gradio execution remains disabled
**Next milestone:** Phase 5.2.6D/E resource authorization and security closure; native Gradio callback/queue integration is deferred and must be separately security-verified before enablement

---

## 1. Purpose

Phase 5 integrates the existing insurance-cost prediction, advisory and insurance-policy RAG capabilities into an authenticated browser interface.

The architecture must preserve the security guarantees established in Phase 4, particularly:

- User and session ownership of insurance-policy documents.
- Backend-controlled authentication and session expiration.
- Separation between users and independent login sessions.
- Secure refresh-token handling.
- Protection against unauthorized document retrieval and deletion.

Phase 5 is being implemented incrementally.

**Phase 5.2.6B is not the completed interactive dashboard.** It establishes server-side authentication integration and trusted Gradio session-issuance primitives. Phase 5.2.6C subsequently added a FastAPI-controlled execution boundary without enabling native Gradio events.

---

## 2. Architectural principles

1. The FastAPI backend remains authoritative for authentication and document authorization.
2. JWT access tokens and refresh credentials remain on the Python server.
3. The browser receives only an opaque HttpOnly browser-identity cookie for authentication continuity.
4. Browser identities and client-supplied Gradio session hashes are untrusted inputs.
5. Every authenticated browser session has an independent credential manager.
6. Successful login rotates the browser identity.
7. Logout clears local authentication and attempts backend revocation.
8. Backend revocation must not be claimed successful unless confirmed.
9. Authentication-changing requests require exact trusted-Origin validation.
10. Gradio event, queue, upload and file routes remain denied until explicitly authorized.
11. Protected callbacks must verify ownership at execution time, not only during page loading.
12. Uploaded insurance-policy documents remain bound to their backend user and session.
13. The frontend runs as a single worker while authentication/session state is process-local.
14. No paid API or infrastructure is introduced without explicit user approval.
15. Local passing tests are not equivalent to production security certification.

---

## 3. System architecture

```text
                    BROWSER
                       |
          Opaque HttpOnly identity cookie
                       |
                       v
              FRONTEND FASTAPI
                       |
        +--------------+---------------+
        |              |               |
    /auth page    Authentication    Mounted Gradio
                  HTTP routes       at /ui
        |              |               |
        |              |        auth_dependency
        |              |               |
        |              |       GradioAuthenticationAdapter
        |              |               |
        +--------------+---------------+
                       |
              HTTPSessionCookies
                       |
              BrowserSessionBinding
                       |
               SessionRegistry
                       |
            SessionCredentialManager
                       |
                FrontendAPIClient
                       |
                       v
                BACKEND FASTAPI
                       |
             Authentication services
             PostgreSQL session state
                       |
              Document authorization
                       |
            Insurance policy RAG
             /                 \
      PostgreSQL             ChromaDB
      document registry      vector store
             \                 /
              Retrieval and reranking
                       |
                Evidence-grounded
                 policy answers
```

The insurance-cost prediction model is a separate application capability. It does not determine insurance-policy coverage or document ownership.

---

## 4. Frontend component responsibilities

### 4.1 `frontend/server.py`

The frontend application entry point.

Responsibilities:

- Construct the FastAPI frontend.
- Initialize authentication and session components.
- Serve the authentication page.
- Handle registration, login, status and logout requests.
- Enforce request-origin and browser-boundary restrictions.
- Mount Gradio under `/ui`.
- Connect Gradio to the authentication adapter.
- Issue trusted Gradio session identifiers.
- Expose a protected FastAPI execution boundary at `POST /frontend-gradio/execute`.
- Preserve restricted access to unapproved Gradio routes.

Current endpoint examples:

| Endpoint | Responsibility |
| --- | --- |
| `GET /` | Initialize or recognize browser identity and redirect to `/auth` |
| `GET /auth` | Render interactive registration/login page |
| `POST /frontend-auth/register` | Register through the backend |
| `POST /frontend-auth/login` | Authenticate and rotate browser identity |
| `GET /frontend-auth/status` | Check frontend authentication status |
| `POST /frontend-auth/logout` | End the frontend session and attempt backend logout |
| `POST /frontend-gradio/session` | Issue a trusted, server-generated Gradio session identifier |
| `POST /frontend-gradio/execute` | Execute the currently supported protected operation after trusted-Origin, authenticated browser, and issued-session ownership checks |
| `/ui` | Restricted mounted Gradio interface |
| `/ui/config` | Authenticated Gradio configuration access |

The session-issuance endpoint does not enable native interactive callbacks. The Phase 5.2.6C execution endpoint is a separate FastAPI-controlled path; native Gradio event and queue routes remain blocked.

### 4.2 `frontend/auth_page.py`

The browser-facing authentication interface.

Responsibilities:

- Present registration and login forms.
- Communicate with same-origin frontend endpoints.
- Avoid exposing backend credentials.
- Apply restrictive browser security policies.

The authentication page uses a response-specific CSP script nonce.

### 4.3 `frontend/auth_coordinator.py`

Coordinates frontend authentication operations with the backend.

Responsibilities include:

- Registration and login orchestration.
- Backend authentication and refresh coordination.
- Logout and error classification.
- Preserving server-side credential ownership.

The coordinator does not grant document access independently of the backend.

### 4.4 `frontend/api_client.py`

HTTP transport between the frontend and backend.

Responsibilities:

- Send backend authentication and application requests.
- Carry credentials on the server side.
- Interpret backend responses.
- Surface controlled transport and API errors.

The browser does not call this Python component directly.

### 4.5 `frontend/session_manager.py`

`SessionCredentialManager` owns credentials for one authenticated frontend session.

Responsibilities:

- Hold access and refresh credentials in server memory.
- Coordinate refresh and credential lifecycle.
- Avoid credential sharing between independent sessions.

It must not be placed in browser-visible Gradio state.

### 4.6 `frontend/session_binding.py`

`SessionRegistry` manages server-side credential-manager references and their lifecycle.

It is an internal ownership and lifecycle component, not a browser authorization credential.

### 4.7 `frontend/http_session.py`

`HTTPSessionCookies` manages the opaque browser-identity cookie.

The cookie identifies a frontend-side browser session. It does not contain the backend JWT or refresh token.

Cookie security requirements include:

- HttpOnly.
- Appropriate SameSite policy.
- Secure flag when deployed over HTTPS.
- Server-side validation against registered identities.

### 4.8 `frontend/browser_session_binding.py`

`BrowserSessionBinding` connects a browser identity to its server-side credential manager.

Responsibilities:

- Register independent browser identities.
- Associate authenticated managers.
- Rotate identities after successful login.
- Resolve current authenticated state.
- Terminate local browser sessions.
- Support authenticated Gradio ownership checks.

**Important distinction:** A method that accepts a browser-provided `session_hash` and verifies the browser is authenticated does not prove that the hash was legitimately issued.

This is why Phase 5.2.6B introduced a separate trusted issuer.

### 4.9 `frontend/gradio_auth.py`

`GradioAuthenticationAdapter` integrates the browser-session system with Gradio's `auth_dependency`.

Authentication flow:

1. Read the browser identity through `HTTPSessionCookies`.
2. Resolve the authenticated manager through `BrowserSessionBinding`.
3. Reject missing, invalid or unauthenticated identities.
4. Return the authenticated browser identity to Gradio.

The adapter never returns backend access or refresh credentials.

Gradio authentication is necessary but not sufficient for callback execution authorization.

### 4.10 `frontend/gradio_security.py`

`GradioSecurityGate` implements fail-closed access restrictions.

Current behavior:

- Permits only explicitly approved shell resources.
- Requires an appropriate browser session.
- Denies unapproved Gradio event and queue endpoints.
- Denies upload and file-serving routes.
- Prevents unrestricted Gradio API exposure.

A narrow authenticated exception exists for `/ui/config`.

Future work must not replace this with a broad `/ui/gradio_api/*` allowlist.

### 4.11 `frontend/gradio_session_issuer.py`

`TrustedGradioSessionIssuer` is the new Phase 5.2.6B component.

Responsibilities:

- Generate unpredictable session identifiers with `secrets.token_urlsafe(32)`.
- Issue identifiers only to authenticated browser identities.
- Record server-side ownership of issued identifiers.
- Enforce a per-browser issuance limit.
- Verify that the requesting browser owns the identifier.
- Recheck current local authentication during verification.
- Revoke issued identifiers explicitly.
- Clear issued state during cleanup.

Default issuance limit: eight identifiers per authenticated browser.

The issuer is process-local and protected by a lock for concurrent access.

**Security principle:** A Gradio session hash is a routing identifier, not an independent authentication credential.

---

## 5. Trusted Gradio session establishment

### 5.1 The original problem

Gradio clients can supply session hashes.

If a server blindly accepts a supplied hash and binds it to the currently authenticated browser, it cannot establish whether that hash belongs to that browser.

An authenticated attacker might attempt to claim or reuse another session identifier.

Therefore, authentication alone does not establish trusted session-hash provenance.

### 5.2 Phase 5.2.6B solution

The frontend now provides:

`POST /frontend-gradio/session`

The endpoint requires:

- A registered authenticated browser identity.
- A valid trusted Origin.
- Successful resolution through the Gradio authentication adapter.

The server then generates a new identifier and records its owner.

```text
Authenticated browser
        |
        | POST /frontend-gradio/session
        | Cookie: opaque browser identity
        | Origin: trusted origin
        v
Frontend FastAPI
        |
        v
GradioAuthenticationAdapter
        |
        v
BrowserSessionBinding.resolve(identity)
        |
        v
TrustedGradioSessionIssuer.issue(identity)
        |
        +-- Generate unpredictable identifier
        +-- Record identifier -> browser identity
        +-- Enforce issuance limit
        |
        v
JSON response:
{
    "session_hash": "<server-generated value>"
}
```

The response uses `Cache-Control: no-store`.

A client-provided session hash is not used as the issued identifier.

### 5.3 Ownership verification

Future protected execution must verify both:

1. The current authenticated browser identity.
2. Ownership of the issued Gradio session identifier.

Conceptual authorization:

```text
Request cookie
    |
    v
Authenticated browser identity
    |
    +-----------------------+
    |                       |
    v                       v
Current authentication    Issued hash ownership
    |                       |
    +-----------+-----------+
                |
                v
        Authorization decision
                |
          Allow or reject
```

A valid hash from another browser must be rejected.

An unknown or attacker-selected hash must be rejected.

A hash from a terminated browser session must be rejected.

### 5.4 Logout and identity rotation

Logout explicitly revokes issued hashes for the browser.

Successful login rotates the browser identity.

Previously issued hashes cannot verify against a different identity.

Termination of the underlying local authentication also prevents subsequent issuer verification.

### 5.5 Current limitation and Phase 5.2.6C decision

The native Gradio browser client is **not configured to use server-issued identifiers**. Instead of overriding undocumented Gradio client internals, Phase 5.2.6C introduced a separate FastAPI-controlled execution path that validates issued identifiers. The native browser-to-Gradio event/queue path remains disabled and is not claimed as verified.

---

## 6. Authentication and authorization are different

Authentication answers:

> Which browser session is making this request?

Authorization answers:

> Is this browser session permitted to execute this specific operation on this specific resource right now?

The current `auth_dependency` establishes the former.

It does not automatically guarantee:

- Safe queued callback execution.
- Protection from delayed events after logout.
- Correct ownership of a supplied session hash.
- Authorization for uploaded files.
- Authorization for downloaded files.
- Ownership of insurance-policy documents.

These checks must be designed and verified independently.

---

## 7. Backend session and document ownership

The backend remains authoritative for:

- User identity.
- PostgreSQL-backed session state.
- JWT validation.
- Refresh-token rotation and revocation.
- Session expiration.
- Insurance-policy document ownership.
- Cross-user and cross-session document isolation.

The intended backend inactivity policy is 30 minutes, sliding according to the existing backend session contract.

The frontend's in-memory issuer does not replace PostgreSQL-backed backend session validation.

In particular, issuer verification does not independently query the backend to detect remote revocation.

Protected backend operations must continue to enforce their own authorization.

---

## 8. Phase 5.2.6A–B verification

### 8.1 Phase 5.2.6A

Completed:

- Reviewed the Gradio authentication and session interfaces.
- Established browser/session trust boundaries.
- Distinguished authentication from execution-time authorization.
- Identified the client-supplied session-hash risk.
- Selected a fail-closed incremental implementation.

Framework version verified in the user's environment:

- Gradio 6.30.0.

### 8.2 Phase 5.2.6B

Completed:

- Implemented `GradioAuthenticationAdapter`.
- Connected Gradio's `auth_dependency`.
- Protected Gradio configuration access.
- Added authenticated browser/session ownership primitives.
- Implemented `TrustedGradioSessionIssuer`.
- Added production session-issuance endpoint.
- Added security unit and integration tests.
- Preserved blocked event, queue, upload and file routes.

### 8.3 Verification results

| Test or check | Observed result |
| --- | --- |
| New trusted-session tests | 15 passed |
| Full default suite | 520 passed |
| Skipped tests | 35 |
| Subtests | 12 passed |
| Source compilation | Passed |
| Git whitespace verification | Passed |
| Source commit | `4818f23` |
| Remote branch | `origin/version_3` |

The results were reported from the user's local environment.

Skipped tests are not counted as passed tests.

These results do not establish production readiness or complete interactive Gradio authorization.

---

## 9. Engineering issues and decisions

### P5.2.6-01 — Untrusted client-generated session hashes

**Risk:** Authentication alone cannot prove ownership of an arbitrary client-supplied hash.

**Decision:** Introduce server-generated identifiers and explicit ownership tracking.

**Implementation:** `TrustedGradioSessionIssuer`.

**Status:** Server-side mitigation implemented and tested. End-to-end client integration remains pending.

### P5.2.6-02 — Authentication versus callback authorization

**Risk:** An authenticated page could still execute an unauthorized callback or queued operation.

**Decision:** Keep event and queue routes denied until execution-time checks are verified.

**Status:** Mitigated for the FastAPI-controlled execution path in Phase 5.2.6C; native callback/queue execution remains intentionally disabled.

### P5.2.6-03 — Process-local authentication state

**Risk:** Multiple frontend workers would not automatically share browser bindings, credentials or issued hashes.

**Decision:** Restrict the current prototype to one frontend worker.

**Status:** Accepted local-development limitation; multi-worker design pending.

### P5.2.6-04 — Backend revocation visibility

**Risk:** A locally issued Gradio identifier does not independently prove the backend session remains active after remote revocation.

**Decision:** Keep backend authorization authoritative; verify execution-time behavior and revocation races in subsequent phases.

**Status:** Backend authority preserved; remote revocation visibility, races and broader security verification remain open.

### P5.2.6-05 — Resource exposure

**Risk:** Broadly enabling Gradio routes could expose event, queue, upload or file functionality without ownership checks.

**Decision:** Preserve the fail-closed gate.

**Status:** Restriction verified; resource-specific authorization pending Phase 5.2.6D.

### P5.2.6-06 — Session issuance resource limits

**Risk:** Repeated issuance can consume process memory.

**Decision:** Cap issued identifiers per browser.

**Implementation:** Default maximum of eight active identifiers.

**Status:** Implemented; comprehensive public-facing rate limiting and resource management remain future work.

---

## 10. Phase 5.2.6C — Original implementation requirements (historical plan)

**Original goal:** Safely connect server-issued sessions to real Gradio interactions. The later implementation deliberately chose a separate FastAPI execution boundary instead; the native Gradio-specific requirements below remain prerequisites if native execution is ever enabled.

Required work:

1. Verify the actual Gradio 6.30.0 client session lifecycle.
2. Establish how the client receives and uses a server-issued identifier.
3. Avoid trusting an attacker-controlled replacement hash.
4. Bind the browser identity and issued identifier for every protected request.
5. Authorize callback execution when it actually occurs.
6. Revalidate queued events immediately before execution.
7. Reject events after logout, identity rotation or expiration.
8. Test cross-browser replay and forged identifiers.
9. Test concurrent requests and session-state races.
10. Preserve backend authorization for every protected operation.

Do not enable protected callbacks until the complete path is verified.

---

## 11. Phase 5.2.6D — Upload and file authorization

Planned responsibilities:

- Authenticate policy-PDF uploads.
- Enforce file size and content-type restrictions.
- Prevent path traversal and unsafe file exposure.
- Enforce user and session ownership.
- Restrict document selection and deletion.
- Prevent cross-user and cross-session file access.
- Verify temporary document cleanup behavior.

Only insurance-policy documents are in scope for the policy RAG feature.

The system is not a general medical-record ingestion platform.

---

## 12. Phase 5.2.6E — Security closure

Required evidence:

- Full regression results.
- Negative security tests.
- Callback and queue ownership verification.
- Upload and file authorization tests.
- Revocation and expiration tests.
- Engineering issue-log reconciliation.
- README and architecture documentation updates.
- Scoped Git review and commit.

A passing local suite is necessary but does not replace a production security assessment.

---

## 13. Phase 5.3 — Authenticated application integration

After the security boundary is established, connect:

- Existing insurance-cost prediction.
- Health-risk and cost advisory.
- Authenticated insurance-policy PDF upload.
- Document selection and lifecycle management.
- Single-policy and multi-policy retrieval.
- Evidence-grounded RAG answers.
- Source-document and page citations.

The numerical cost estimate remains the responsibility of the trained ML model.

The LLM may explain the prediction and answer policy questions, but must not be treated as an authoritative insurance coverage decision-maker.

---

## 14. Deployment and cost constraints

Current development assumptions:

- Local development environment.
- One frontend worker.
- In-memory frontend credentials and session issuance.
- PostgreSQL and ChromaDB for backend state and document retrieval.
- Synthetic test data.
- No chargeable API calls without approval.

Before public deployment, separately review:

- HTTPS and secure cookies.
- Reverse-proxy and trusted-host configuration.
- Shared session storage and atomic ownership operations.
- Rate limiting.
- CSRF protections.
- Logging and secret redaction.
- Session cleanup and resource exhaustion.
- File security.
- Monitoring and recovery.
- Privacy requirements.
- Load and concurrency testing.
- External security review.

---

## 15. Version-control record

Latest verified source milestone:

```text
4818f23 (HEAD -> version_3, origin/version_3)
feat(auth): complete Phase 5.2.6B trusted Gradio sessions
```

The source commit contains 12 changed or added files covering:

- Browser-session ownership.
- Gradio authentication.
- Trusted session issuance.
- Frontend production wiring.
- Unit tests.
- Integration and security regression tests.

The documentation update should be committed separately.

Do not stage unrelated local artifacts:

```text
docs/research/
tests/evaluation/phase447c_performance.local.json
tests/evaluation/phase447c_retrieval_results.local.json
```

---

## 16. Acceptance decision

**Phase 5.2.6A: COMPLETE.**

**Phase 5.2.6B: COMPLETE for its server-side authentication and trusted-session-issuance scope.**

**Phase 5.2.6C: COMPLETE for the FastAPI-controlled secure execution boundary; native Gradio callback/queue execution is not enabled.**

The architecture is intentionally fail-closed.

Interactive Gradio callbacks, queues, uploads and file-serving operations remain blocked until their authorization paths are implemented and verified.

**Next engineering action:** Proceed to Phase 5.2.6D/E resource authorization and security closure. Revisit native Gradio event/queue integration only with admission, execution and result-ownership protections and dedicated verification.

### Phase 5.2.6C — Native Gradio Route Security Verification

**Status:** FastAPI-controlled execution boundary implemented and regression-tested. Native Gradio execution intentionally disabled.

**Verification results (8 November 2026):**
- Phase 5.2.6C integration tests: 12 passed.
- Full regression suite: 546 passed, 35 skipped, 12 subtests passed (prior run).
- Anonymous requests to `/ui/queue/join`, `/ui/call/v2/verify_session`, `/ui/call/verify_session`, and `/ui/queue/data` were rejected with HTTP 401.
- The existing authenticated-route denial test remains part of the integration suite.

**Security decisions:**

1. The FastAPI-controlled `/frontend-gradio/execute` endpoint remains the protected execution boundary.
2. Server-issued session hashes are validated against authenticated browser ownership before protected execution.
3. Native Gradio event and queue endpoints remain blocked by the default-deny security gate.
4. Native Gradio callbacks, queue execution, and queue-result access have not been enabled or security-verified.
5. Insurance-policy upload and file-serving endpoints remain outside the enabled native Gradio execution surface.

**Residual limitations:**

The current tests demonstrate that the configured routes reject the tested unauthorized requests. They do not establish security for native Gradio event processing, queued-job execution, or cross-browser result retrieval if those routes are enabled later.

**Future requirement:**

Before enabling native Gradio events, implement and verify admission-time authorization, execution-time reauthorization, queue-result ownership checks, and revocation behavior following logout or session expiry.

**Engineering decision:** Keep native Gradio event and queue routes disabled unless a future feature explicitly requires them and the additional security controls have been implemented and tested.

---

## 17. Phase 5.2.6C — Implementation and security closure record (8 November 2026)

### 17.1 Scope and implementation files

This section updates the historical Phase 5.2.6B architecture and planning sections above; it does not erase earlier decisions or test checkpoints. Phase 5.2.6C implements a **FastAPI-controlled** execution path, not native Gradio callback or queue processing.

- `frontend/server.py`: adds `POST /frontend-gradio/execute` as a controlled, authenticated frontend entry point with trusted-Origin checks, bounded request handling and server-issued session ownership verification before invoking the supported protected operation.
- `frontend/gradio_execution_authorizer.py`: resolves the issued hash against the authenticated browser, verifies the current credential manager and obtains the server-held access credential for authorized execution. Backend authorization remains authoritative.
- `frontend/gradio_protected_callbacks.py`: contains a request-context authorization helper for possible future native callback use; this is **not** evidence that native callbacks are registered or enabled.
- `frontend/gradio_session_issuer.py` and `frontend/gradio_auth.py`: existing Phase 5.2.6B issuer and authentication adapter are reused.
- `frontend/gradio_security.py`: retains default-deny native Gradio event, queue, upload and file routes. No broad allowlist was introduced.
- `tests/unit_tests/test_gradio_execution_authorizer.py`, `tests/unit_tests/test_gradio_protected_callbacks.py`, and `tests/integration_tests/test_phase526c_secure_execution_boundary.py`: targeted authorization and endpoint regressions.

### 17.2 Security issues, decisions and outcomes

| Issue / threat | Mitigation or decision | Verification scope / residual risk |
| --- | --- | --- |
| Client-generated Gradio session hash cannot prove ownership | Require a trusted, server-issued hash for the FastAPI execution boundary | Does not change native Gradio client hash behavior |
| Authenticated page is not authorization to execute an event | Revalidate authenticated browser and issuer ownership before protected FastAPI execution | Native Gradio preprocessing and callbacks remain blocked |
| Cross-browser or forged hash reuse | Verify browser-to-issued-hash ownership, reject missing or unknown identifiers | Covered by focused tests; not a general penetration test |
| Logout, rotation and local session revocation | Issuer verification re-resolves current local authentication | Backend remote revocation is enforced by backend protected operations; asynchronous race coverage remains future work |
| Queue submission may preprocess or validate inputs before callback | Keep native `/ui/queue/join` and `/ui/call/*` routes denied | Native queue execution is not tested as enabled |
| Queue-result leakage | Keep `/ui/queue/data` and native result routes denied | Ownership enforcement required before future enablement |
| Unreviewed upload and file routes | Keep native Gradio upload/file access disabled | Dedicated Phase 5.2.6D implementation pending |
| Process-local session state | Maintain one frontend worker for the local prototype | Shared multi-worker state and distributed coordination remain future work |

### 17.3 Verified checkpoints (user-reported terminal output)

- Earlier Phase 5.2.6B full default suite: **520 passed, 35 skipped, 12 subtests passed**.
- Phase 5.2.6C intermediate full suite: **532 passed, 35 skipped, 12 subtests passed**.
- Phase 5.2.6C focused tests after the protected execution implementation: **26 passed**.
- Phase 5.2.6C full default regression: **546 passed, 35 skipped, 12 subtests passed**.
- Subsequent integration test rerun after adding anonymous native-route denial cases: **12 passed**. The full 546-test suite was **not reported rerun after that final test-only change**.
- Manual unauthenticated requests to `/ui/queue/join`, `/ui/call/v2/verify_session`, `/ui/call/verify_session`, and `/ui/queue/data?session_hash=forged` each returned **HTTP 401**. The corresponding anonymous denial cases were then added to automated integration coverage.

These are local, user-reported results. They do not establish production security, native queue authorization, or external penetration-test coverage.

### 17.4 Operational flow and remaining acceptance boundaries

```text
Authenticated browser + opaque HttpOnly cookie
       |
       +--> POST /frontend-gradio/session
       |       -> trusted Origin + current browser identity
       |       -> server-issued, browser-owned session_hash
       |
       +--> POST /frontend-gradio/execute
               -> trusted Origin and bounded request
               -> current authenticated browser identity
               -> verify server-issued session_hash ownership
               -> protected FastAPI operation
               -> backend JWT + active DB session and document ownership

/ui/call/*, /ui/queue/*, native uploads and files
       -> remain denied by GradioSecurityGate
```

The FastAPI execution boundary must not be described as full interactive Gradio dashboard integration. Before native events are enabled, implement **admission-time checks before preprocessing, execution-time reauthorization, queue/result ownership validation and logout/expiry race tests**. Phase 5.2.6D/E still cover authenticated PDF resource handling, additional adversarial tests, issue-log reconciliation and the final broader Phase 5.2.6 closure.

### 17.5 Version-control and documentation discipline

The last confirmed committed source checkpoint is `4818f23` (Phase 5.2.6B), with documentation commit `aca267b`. The Phase 5.2.6C code and documentation should be staged explicitly and reviewed before committing. The Phase 5.2.6C commit hash is **not known** at documentation-authoring time. Do not stage local evaluation artifacts, secrets, vector stores, or unrelated research files. No paid APIs or infrastructure were required for the reported tests.
