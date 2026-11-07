
# Phase 5 — Authenticated Frontend Architecture and Engineering Record

**Project:** GenAI Health Risk & Cost Advisor V3  
**Branch:** `version_3`  
**Last updated:** 7 November 2026  
**Frontend:** FastAPI with mounted Gradio 6.30.0  
**Backend:** FastAPI, PostgreSQL-backed authentication and document ownership  
**Latest source commit:** `4818f23` — `feat(auth): complete Phase 5.2.6B trusted Gradio sessions`  
**Current milestone:** Phase 5.2.6B server-side implementation complete and verified  
**Next milestone:** Phase 5.2.6C — trusted Gradio client integration, callback and queue authorization

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

**Phase 5.2.6B is not the completed interactive dashboard.** It establishes server-side authentication integration and trusted Gradio session-issuance primitives.

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
| `/ui` | Restricted mounted Gradio interface |
| `/ui/config` | Authenticated Gradio configuration access |

The session-issuance endpoint does not enable interactive callbacks.

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

### 5.5 Current limitation

The actual Gradio browser client is **not yet configured to use these server-issued identifiers**.

Therefore, the trusted issuer is implemented and verified as a server-side component, but the full browser-to-Gradio execution path is not yet complete.

Phase 5.2.6C must resolve this before callbacks are enabled.

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

**Status:** Open for Phase 5.2.6C.

### P5.2.6-03 — Process-local authentication state

**Risk:** Multiple frontend workers would not automatically share browser bindings, credentials or issued hashes.

**Decision:** Restrict the current prototype to one frontend worker.

**Status:** Accepted local-development limitation; multi-worker design pending.

### P5.2.6-04 — Backend revocation visibility

**Risk:** A locally issued Gradio identifier does not independently prove the backend session remains active after remote revocation.

**Decision:** Keep backend authorization authoritative; verify execution-time behavior and revocation races in subsequent phases.

**Status:** Open for Phase 5.2.6C and broader security verification.

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

## 10. Phase 5.2.6C — Next implementation

**Goal:** Safely connect server-issued sessions to real Gradio interactions.

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

**Phase 5.2.6C: NOT STARTED.**

The architecture is intentionally fail-closed.

Interactive Gradio callbacks, queues, uploads and file-serving operations remain blocked until their authorization paths are implemented and verified.

**Next engineering action:** Begin Phase 5.2.6C with the Gradio 6.30.0 client/session lifecycle and the execution-time authorization contract.