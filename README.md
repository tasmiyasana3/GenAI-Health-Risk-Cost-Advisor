# Insurance Cost & Document Advisor — V3 (in development)

An experimental insurance analytics application combining a trained machine learning pipeline, Gemini-generated customer advisories, and document-based question answering. Built with Python and Gradio, this project explores how predictive modeling and retrieval-augmented generation (RAG) can work together in a user-facing application.

> **Disclaimer:** This is a portfolio and research demonstration. Predictions are not insurance quotations, underwriting decisions, or medical advice. The PDF question-answering feature should not be relied on to determine coverage without reviewing the original policy.

## What the application does

The original V2 Gradio experience is documented below. V3 adds a FastAPI backend, persistent insurance-policy retrieval, a PostgreSQL document registry, and the beginnings of account authentication. **The V3 backend and registration endpoint are not yet a deployed, authenticated multi-user product.**

The application has two independent workflows:

**Insurance cost estimation:** A user enters insurance and health-related attributes. The application validates the inputs, loads a saved scikit-learn prediction pipeline, and returns an estimated cost. Gemini uses that estimate, the customer profile, and historical dataset averages to prepare an explanatory summary and a customer email draft. **Gemini does not calculate the predicted cost.**

**Ask an insurance PDF (V2 baseline):** A user uploads a text-based PDF and asks a question. The application extracts text, splits it into overlapping passages, ranks passages with TF-IDF and cosine similarity, and asks Gemini to answer using the retrieved excerpts with page references. **V3** develops a separate persistent, semantic retrieval workflow; see the V3 section below.

## What's new in V2

V2 moves the project from a notebook-oriented prototype toward a modular application with reusable inference services and a separate document Q&A workflow.

### Changes to the original ML workflow

The original exploratory analysis and core modeling objective were retained. The revised training workflow addresses several methodological issues identified in the earlier notebook:

| Area | Revision | Why it matters |
| --- | --- | --- |
| Column consistency | Standardized `regular_checkup_lasy_year` to `regular_checkup_last_year` in the modeling data | Keeps feature names consistent between training and inference |
| Categorical values | Corrected `Salried` to `Salaried` | Avoids unintended duplicate categories |
| Preprocessing leakage | Moved learned imputation, encoding, and applicable outlier thresholds into training-fold pipelines | Prevents information from validation/test data influencing preprocessing |
| Missing BMI | Fit median imputation using training data rather than the complete dataset | Supports a more defensible evaluation |
| Admission history | Treated missing `Year_last_admitted` as **unknown**, not automatically as never admitted; introduced recorded-status/category features | Avoids making an unsupported clinical assumption |
| Admission-year arithmetic | Removed the unsupported fixed-reference-year calculation | Avoids a misleading derived feature |
| Outliers | Preserved exploratory outlier analysis while comparing clipping strategies without automatically clipping the target | Separates exploratory observations from model-training decisions |
| Model development | Compared baseline and advanced regression candidates, with training-data cross-validation and validation RMSE used for selection | Makes model selection more systematic |
| Experimental features | Evaluated alternative feature sets, including an exploratory health-risk-score variant | Tests whether extra engineered features actually help |
| Reproducible inference | Exported a fitted scikit-learn pipeline and training metadata | Allows the application to predict without rerunning the notebook |

The revised notebook includes evaluation and diagnostic steps, but **this README does not claim a particular accuracy improvement** without confirming the saved `models/training_report.json`. The V2 application is described as using the exported XGBoost-based pipeline; its exact fitted configuration should be verified from the model artifact and training report.

### Application changes

- Separated model inference (`services/ml_service.py`) from the Gradio interface (`app.py`).
- Added required-feature validation and cached loading of the exported pipeline.
- Connected Gemini advisories to the **ML-generated estimate**, rather than asking the LLM to invent a premium.
- Added historical reference statistics through `services/data_service.py`.
- Added a PDF Q&A tab using TF-IDF retrieval, cosine similarity, and Gemini.
- Added a basic pytest test for missing model inputs.
- Improved error handling so an advisory-generation failure does not discard a successful ML estimate.

## V2 architecture (historical baseline)

```text
                         Gradio (app.py)
                         /             \
                Cost prediction       Ask an insurance PDF
                       |                      |
              services/ml_service.py   services/rag_service.py
                       |                      |
              Saved fitted pipeline    PDF text extraction (pypdf)
                       |                      |
               Numerical estimate      Overlapping text chunks
                       |                      |
          services/advisory_service.py  TF-IDF vectors + cosine similarity
                       |                      |
               Gemini advisory         Top relevant excerpts + page labels
                       |                      |
               Summary + email         Gemini answer with page references

               config.py supplies shared Gemini configuration
```

The prediction and PDF workflows are independent; document retrieval does not currently change the insurance cost estimate.

## V2 RAG approach: TF-IDF baseline

1. Read a PDF using `pypdf` and preserve page numbers.
2. Normalize whitespace and split each page into passages of up to **1,100 characters**, starting a new passage every **900 characters** (approximately **200 characters of overlap** between full consecutive passages).
3. Fit a `TfidfVectorizer` on the passages for the uploaded document.
4. Transform the user's question into the same TF-IDF feature space.
5. Use cosine similarity to select up to **four** matching passages.
6. Send the retrieved excerpts and their page labels to Gemini, asking it to answer only from the supplied context.

This is a **keyword-based retrieval baseline**. It does not yet use semantic embedding models, ChromaDB, or a persistent vector index. PDF extraction and vectorization run again for each question. Page references in generated answers are prompted, not independently verified. Scanned/image-only PDFs are not supported without OCR.

**V3 update:** semantic retrieval, persistent ChromaDB indexing, and a PostgreSQL document registry have since been implemented in the V3 development branch. Comparative retrieval evaluation remains future work.

## V2 project structure (historical reference)

```text
GenAI-Health-Risk-Cost-Advisor/
├── app.py                       # Gradio interface and event handlers
├── config.py                    # Project paths and Gemini client
├── insurance_transformers.py   # Custom preprocessing for saved pipeline
├── data/
│   └── Data.csv                 # Local training/reference dataset
├── notebooks/
│   └── Insurance_Cost_Integrated_Corrected_final.ipynb
├── models/
│   ├── insurance_pipeline.joblib
│   └── training_report.json
├── services/
│   ├── ml_service.py            # Model loading and inference
│   ├── data_service.py          # Historical dataset statistics
│   ├── advisory_service.py      # Gemini explanation and email
│   └── rag_service.py           # PDF extraction, retrieval, answer generation
├── tests/
│   └── test_ml_service.py
├── docs/
│   └── screenshots/              # Local demonstration screenshots
├── requirements.txt
└── README.md
```

## V2 local Gradio setup

Requirements: Python environment with the dependencies in `requirements.txt`, a fitted model artifact, and a Gemini API key.

```bash
# From the project root
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Create a local `.env` file:

```dotenv
GOOGLE_API_KEY=your_api_key_here
GEMINI_MODEL=your_supported_gemini_model
```

Never commit `.env` or your API key. The selected Gemini model must be supported by your account and integration.

The notebook is responsible for training and exporting `models/insurance_pipeline.joblib`. The companion `insurance_transformers.py` must be importable when the model is loaded. If you change feature engineering or preprocessing, retrain and re-export the pipeline.

Run the application:

```bash
python app.py
```

Open the local URL displayed in the terminal (typically `http://127.0.0.1:7860`).

Run the original V2 validation test:

```bash
python -m pytest tests/test_ml_service.py -v
```

## V2 verification performed

- Exported the fitted pipeline and successfully reloaded it using `joblib`.
- Generated a prediction through `services/ml_service.py` using a dataset row.
- Confirmed the Gradio cost prediction and Gemini advisory render locally.
- Confirmed the PDF Q&A flow retrieves the example policy's **24-month pre-existing-condition waiting period** and displays a Page 1 reference.
- Tested a question about maternity coverage absent from the sample policy; the generated response acknowledged insufficient information and cited Page 2.
- Passed the missing-input validation test (`test_missing_fields`).

These are initial smoke tests, not a comprehensive model, RAG, or security evaluation.

## Application screenshots

The following examples were captured from the locally running Gradio application using **fictional demonstration data**. Outputs are illustrative and do not represent insurance quotations.

### Insurance cost estimate

For the sample profile *Alexander Wright*, the saved ML pipeline returned an estimated insurance cost of **30,990.95**. The Gemini advisory compares this with the dataset reference average of **27,147.41**; these values are specific to this example and dataset.

![Insurance cost prediction](docs/screenshots/cost-prediction.png)

### Customer-facing advisory draft

Gemini uses the model estimate to generate an explanatory message and a draft customer email; it does **not** determine the numerical prediction.

![Customer advisory](docs/screenshots/customer-advisory.png)

### PDF question answering

For the fictional sample policy, the question *“What is the waiting period for pre-existing conditions?”* returned **24 months (Page 1)**. The system uses TF-IDF and cosine similarity to retrieve passages before sending them to Gemini.

![PDF question answering](docs/screenshots/pdf-question-answering.png)

The screenshots demonstrate local functionality, not an independently audited RAG evaluation. 

### Unsupported-question handling

As a basic grounding check, the same sample policy was asked: *“Does this insurance policy cover maternity expenses, and what is the maximum maternity benefit amount?”*

The application responded that the document **does not describe maternity benefits (Page 2)** and that there is **insufficient information** to establish maternity coverage or a maximum benefit amount. It did not invent a policy limit.

![Unsupported question handling](docs/screenshots/unsupported-question.png)

This is **one successful test case**, not proof that the system always avoids hallucinations or that its page citations are independently verified. The source document's actual terms must be reviewed for consequential decisions.

## V2 deployment history

The V2 application was demonstrated locally. **V2 was not deployed to the existing Hugging Face Space.** The existing Space hosts an earlier version. The plan is to preserve V2 in Git and update the existing Space when a later version is ready. For any future deployment, include runtime dependencies, the exported model and custom transformer module, and configure `GOOGLE_API_KEY` as a Space secret. Never commit `.env`.

## V2 limitations and next steps

- Insurance cost predictions are experimental and should not be used for actual pricing or coverage decisions.
- The exploratory health-risk score is not a clinically validated measure.
- The PDF reader supports text-extractable PDFs only, up to the configured 100-page limit.
- TF-IDF may miss relevant passages when question wording differs substantially from the document.
- The RAG system currently reprocesses documents on every question and does not independently verify citations.
- Uploaded policy documents and retrieved excerpts should be handled with appropriate privacy controls before any real-user deployment.
- Future work includes semantic retrieval with ChromaDB, stronger document isolation, retrieval benchmarks, additional automated tests, and deployment validation.


---

## V3 engineering progress — Phases 1–4.2

### Phase-by-phase implementation history

This README records each completed milestone separately. **Phase 4.1 established the PostgreSQL schema and safe migration process; Phase 4.2 built user registration on that foundation.** Both are completed and independently verified.

| Milestone | What was built | Verification |
| --- | --- | --- |
| Phase 1 | Semantic document retrieval and reranking | Local retrieval workflow completed |
| Phase 2 | FastAPI endpoints and persistent document indexing | Local API and indexing workflow completed |
| Phase 3 | PostgreSQL document registry, multiple document retrieval, filename/page citations | Local registry and retrieval workflow completed |
| **Phase 4.1** | **Versioned migrations, `users` table, nullable document owner, migration history/checksums, safe rollback and backup/restore checks** | **Migration idempotency, checksum enforcement, rollback, schema parity and restore verified** |
| **Phase 4.2** | **Registration endpoint, Argon2id password security, database access and reusable automated tests** | **18 reusable tests passed; 65 full-suite tests passed with 6 intentional skips** |


V3 development takes place on the **`version_3` Git branch**. The original insurance-cost prediction and Gemini advisory remain distinct from insurance-policy question answering: **RAG answers do not determine or modify the ML cost estimate.**

### Completed functionality

| Phase | Implementation | State |
| --- | --- | --- |
| 1 | Semantic RAG retrieval and reranking | Completed locally |
| 2 | FastAPI backend and persistent document indexing | Completed locally |
| 3 | PostgreSQL document registry, multi-document retrieval, filename/page citations | Completed locally |
| 4.1 | Versioned PostgreSQL migrations, user schema, document ownership field, migration checksums and restore checks | Completed and verified |
| 4.2 | User registration, Argon2id password hashing, email validation, duplicate handling and reusable tests | Completed and verified |

**Important:** Registration is implemented, but login, JWT authorization, Google OAuth, ownership enforcement, and a fully authenticated Gradio interface are **not yet implemented**. The `documents.user_id` column exists but is nullable; the existing sample policies have no assigned user. Do not assume that a registered user is already isolated from other users' documents.

### V3 architecture (current development state)

```text
                        Existing Gradio interface (V2)
                           |                |
                 ML cost estimation    Gemini advisory
                           |
                  Saved sklearn pipeline

                     FastAPI backend (V3)
                 /           |            \
          /predict      /documents*     /auth/register
              |             |                 |
       ML services      Document/RAG       Pydantic EmailStr
                           services         + password rules
                              |                 |
                      PDF text extraction   Argon2id hashing
                              |                 |
                      Chunking + semantic    PostgreSQL users
                      embeddings / retrieval
                              |
                       Persistent ChromaDB
                              |
                  PostgreSQL document registry
                 (status, collection, filename,
                    optional owner/user_id)
                              |
                  Gemini grounded policy answer
                    + filename/page citations

       *Document endpoints are not yet protected by JWT.
       Authentication and ownership checks are future Phase 4 work.
```

FastAPI separates HTTP request handling from reusable service logic. PostgreSQL tracks document/account metadata and migration history; ChromaDB stores document embeddings for retrieval. The application uses Gemini to formulate grounded answers from retrieved insurance-policy passages. This is **insurance-policy document intelligence**, not a medical-record diagnosis workflow.

### Phase 4.1 — PostgreSQL schema, migrations, ownership groundwork and recovery

**Why this phase was necessary:** Before adding accounts, the backend needed a repeatable way to create and evolve database tables. A developer should be able to apply the same schema changes to a fresh database without manually editing tables or silently changing previously applied migrations. The document registry also needed a place to record which user owns each insurance-policy PDF, even though ownership enforcement would come later.

**Database environments used:**

| Database | Purpose | Important boundary |
| --- | --- | --- |
| `health_rag_db` | Working local application database | Contains existing insurance-policy document metadata; not a target for destructive integration tests |
| `health_rag_migration_test` | Isolated migration and registration test database | Used for migration checks and temporary test accounts |
| `health_rag_restore_test` | Backup/restore verification database | Used to confirm recovery and compare restored schema/data |

**Schema created or extended:**

| Table | Important fields | Purpose |
| --- | --- | --- |
| `public.users` | `user_id` (UUID primary key), `email` (unique), `password_hash` (nullable), `created_at` | Account identity and eventual password authentication |
| `public.documents` | `document_id`, `filename`, `collection_name`, `status`, `uploaded_at`, `user_id` | Registry of indexed PDFs; `user_id` is a nullable foreign key to `users.user_id` |
| `public.schema_migrations` | `version`, `description`, `applied_at`, `checksum` | Records applied SQL migrations and detects later changes to migration files |

The `documents.user_id` field was intentionally **nullable** to preserve the existing sample policy records while adding the ownership schema. At the end of Phase 4.1, the working database retained two ready policy PDFs with no assigned owner (`user_id IS NULL`). **A foreign-key field is not authorization:** access control must still be implemented in Phase 4.5.

**Migration files, in execution order:**

| File | Purpose |
| --- | --- |
| `database/migrations/001_create_users.sql` | Create the `users` table |
| `database/migrations/002_add_document_ownership.sql` | Add the nullable `documents.user_id` foreign key |
| `database/migrations/003_create_migration_history.sql` | Establish the migration-history table |
| `database/migrations/004_add_migration_checksums.sql` | Add checksums for migration integrity |
| `database/migrate.py` | Python migration runner that applies and verifies versioned SQL files |

**How the migration runner protects the database:**

1. Checks the migration history to identify which versions are already applied, so re-running it does not blindly repeat changes (**idempotency**).
2. Computes SHA-256 checksums of migration files and compares them with recorded values, so edited migrations can be detected.
3. Uses a PostgreSQL advisory lock to reduce the risk of concurrent migration runners interfering with each other.
4. Executes migrations transactionally, so a failing migration is rolled back rather than leaving partially applied schema changes.
5. Supports the verified legacy-baseline/backfill path for the existing database schema.

**Tests and experiments performed during Phase 4.1:**

- Verified that the migration runner could apply a temporary migration and skip it safely when rerun.
- Intentionally tested a failing temporary migration and confirmed transaction rollback.
- Verified migration checksums and detection of unexpected migration-file changes.
- Tested PostgreSQL backup/restore into `health_rag_restore_test` and compared the restored schema with the working database.
- Confirmed the working registry retained the two existing ready policy PDFs and the test database could remain free of policy documents.
- Verified database role permissions, including the principle that the application role should not have broad destructive privileges.

**Phase 4.1 result:** Database structure, migration history, checksum protection and recovery checks were completed before implementing registration. The later `test_phase41_database.py` file preserves read-only regression checks for key Phase 4.1 schema and permission requirements.

**Remaining work from this foundation:** Phase 4.2 added user registration, Phase 4.5 will enforce per-user document access, and Phase 8 will add CI test-server isolation, deployment migration procedures and operational backup planning.

### Phase 4.2 — Registration and password security

| File | Responsibility |
| --- | --- |
| `services/auth_service.py` | Validate passwords; hash and verify them with Argon2id; reject malformed stored hashes safely |
| `services/database_service.py` | Create users and retrieve users by email using PostgreSQL |
| `api/auth_routes.py` | `POST /auth/register`, request validation and HTTP response/error mapping |
| `api/main.py` | Includes the authentication router in the existing FastAPI app |
| `tests/reusable_tests/conftest.py` | Shared pytest fixture that opts into database tests and verifies isolated database connections |
| `tests/reusable_tests/test_phase41_database.py` | Read-only schema, migration and database-role permission checks |
| `tests/reusable_tests/test_phase42_passwords.py` | Password hashing, verification and invalid-input unit tests |
| `tests/reusable_tests/test_phase42_api_validation.py` | Registration route discovery and request-validation tests |
| `tests/reusable_tests/test_phase42_registration_db.py` | HTTP-to-PostgreSQL registration integration test with temporary-account cleanup |

**Registration request:** `POST /auth/register` with JSON fields `email` and `password`. A successful registration returns **HTTP 201** with `user_id`, normalized `email`, and `created_at`; it does **not** return the password or password hash. Duplicate emails return **409**, and invalid email/password inputs return **422**. A PostgreSQL registration failure is reported as **503** rather than exposing internal database details.

Passwords must have at least 12 characters and cannot exceed 1,024 UTF-8 bytes. The application uses `pwdlib[argon2]`; malformed stored hashes are handled by catching `UnknownHashError` and returning a failed verification rather than crashing.

### V3 local setup (development)

Use the existing Python virtual environment and `requirements.txt`:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

The V3 backend additionally requires a running, correctly configured PostgreSQL instance and persistent vector-storage configuration. Set environment variables locally, not in Git. Illustrative variable names from the current local setup:

```dotenv
GOOGLE_API_KEY=your_api_key_here
GEMINI_MODEL=your_supported_gemini_model
DB_NAME=health_rag_db
```

Other PostgreSQL connection settings must match `services/database_service.py` and your local environment. **Do not use these illustrative values as production credentials.** Apply migrations according to the repository's migration runner before using a new database. For local API development, start the FastAPI app using:

```bash
python -m uvicorn api.main:app --reload
```

FastAPI's interactive API documentation is normally available at `http://127.0.0.1:8000/docs`. The original Gradio application can still be started with `python app.py`; the authenticated V3 Gradio-to-FastAPI integration is planned for Phase 5.

### Testing and verified results (Phase 4.2)

`pytest` is a Python testing framework. `python -m pytest -q` discovers tests and runs them in quiet mode; it is not a folder. The reusable tests live in `tests/reusable_tests/`.

```bash
# All normal tests; database integration tests remain disabled by default.
python -m pytest -q

# Explicitly enable isolated PostgreSQL integration tests.
RUN_PHASE4_DB_TESTS=1 python -m pytest -q tests/reusable_tests

# Explain any intentionally skipped tests.
python -m pytest -q -rs
```

**Verified locally at the end of Phase 4.2:**

- Reusable suite with database integration enabled: **18 passed**.
- Full project suite with database integration disabled: **65 passed, 6 skipped**.
- All six skips were intentional PostgreSQL tests requiring `RUN_PHASE4_DB_TESTS=1`.

The shared `conftest.py` fixture temporarily sets `DB_NAME=health_rag_migration_test`, checks `current_database()` on the actual application connection, verifies the owner cleanup connection, and restores the environment after testing. It does **not** change `.env` permanently. Database tests must be explicitly enabled. This is a local safeguard, not a substitute for a dedicated isolated PostgreSQL server and CI secrets in deployment.

### Engineering issues encountered and resolved

| Issue | Resolution / outcome |
| --- | --- |
| Application role could not insert users into the test database | Granted limited `SELECT` and `INSERT` permissions on `public.users`; no `DELETE` for the application role |
| FastAPI route-inspection helper appeared to miss `/auth/register` | The helper incorrectly assumed every route had a `.path` attribute; the generated OpenAPI schema confirmed the route existed |
| `pwdlib` raised `UnknownHashError` for a malformed stored hash | Updated `verify_password()` to catch the exception; regression test passed |
| Database tests initially blocked because `.env` pointed to `health_rag_db` | Updated the shared pytest fixture to temporarily select the isolated test database and verify the actual connection |
| macOS PyTorch redirect warning | Recorded as a harmless environment warning, not a registration failure |

**Known follow-ups:** The local test owner role is hardcoded and the fixture checks the database name but not the identity of the PostgreSQL server. CI/CD must use dedicated test infrastructure, nonproduction credentials, and stronger connection isolation. The normal working database may need matching least-privilege registration grants before registration is exercised there; permissions verified in the isolated test database do not prove production permissions.

### V3 repository additions (selected files)

```text
GenAI-Health-Risk-Cost-Advisor/
├── app.py                         # Existing Gradio application
├── api/
│   ├── main.py                    # FastAPI app and existing endpoints
│   └── auth_routes.py             # Phase 4.2 registration endpoint
├── database/
│   ├── migrate.py                 # Versioned SQL migration runner
│   └── migrations/
│       ├── 001_create_users.sql
│       ├── 002_add_document_ownership.sql
│       ├── 003_create_migration_history.sql
│       └── 004_add_migration_checksums.sql
├── services/
│   ├── ml_service.py
│   ├── data_service.py
│   ├── advisory_service.py
│   ├── rag_service.py
│   ├── database_service.py
│   └── auth_service.py
├── tests/
│   ├── test_ml_service.py
│   └── reusable_tests/
│       ├── conftest.py
│       ├── test_phase41_database.py
│       ├── test_phase42_passwords.py
│       ├── test_phase42_api_validation.py
│       └── test_phase42_registration_db.py
├── requirements.txt
└── README.md
```

This tree highlights relevant files and does **not** attempt to enumerate every existing V3 module or test. Consult the repository for the authoritative complete layout.

## Revised V3 development roadmap

All development continues on the **`version_3` branch** until the next reviewed merge/release.

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Semantic RAG retrieval and reranking | Done |
| 2 | FastAPI and persistent document indexing | Done |
| 3 | PostgreSQL registry, multi-document retrieval, filename/page citations | Done |
| 4.1 | Database migrations, users table and ownership schema | Done |
| 4.2 | Registration, Argon2id, reusable tests and database safety fixture | Done |
| 4.3 | Login and JWT issuance/validation | Next |
| 4.4 | Protect API endpoints with token-based authentication | Pending |
| 4.5 | Enforce per-user PostgreSQL and ChromaDB document ownership | Pending |
| 4.6 | Authentication, authorization and ownership security tests | Pending |
| 4.7 | Google OAuth integration and account-linking design | Pending (part of original Phase 4 scope) |
| 5 | Gradio interface connected to authenticated FastAPI backend | Pending |
| 6 | Validation, error handling, security hardening and automated end-to-end testing | Pending |
| 7 | Performance, resource usage and retrieval evaluation against the V2 baseline | Pending |
| 8 | Docker, GitHub Actions CI/CD, Hugging Face Spaces deployment and remote-user testing | Pending |

**Phase 8 hosting plan:** evaluate deploying the user-facing Gradio interface to the existing Hugging Face Space, with a suitable FastAPI backend and **durable external PostgreSQL/vector storage**. The Space's ephemeral filesystem must not be treated as permanent storage for user policies or accounts. Configure API keys, database credentials, and JWT signing secrets through deployment secrets; never commit them. Decide the final architecture and access controls before exposing the application to external users.

## Current limitations and security boundaries

- V3 is still a local development system; registration does **not** mean login, JWT authentication, or multi-user isolation is complete.
- Existing document records may have `user_id = NULL`. Enforce ownership before accepting real-user insurance documents.
- Uploaded insurance-policy PDFs can contain sensitive personal or financial information; use fictional or explicitly authorized test data during development.
- The model estimate is not an insurance quote or medical diagnosis, and Gemini-generated text is not authoritative coverage advice.
- Retrieval citations and grounding require systematic evaluation; successful demonstration examples are not guarantees.
- CI/CD, remote deployment, operational backups, rate limiting, production secret management, and independent test-server verification remain future work.

## Version history

- **V2:** modular scikit-learn insurance cost inference, Gemini advisory, Gradio UI, and TF-IDF PDF question-answering baseline. Historical details and screenshots are retained above.
- **V3 Phases 1–3:** semantic RAG, persistent document indexing, FastAPI, PostgreSQL registry and source citations.
- **V3 Phase 4.1:** versioned PostgreSQL schema migrations and user/document ownership groundwork.
- **V3 Phase 4.2:** registration endpoint, Argon2id password handling, database integration and reusable tests. Verified locally: 18 reusable tests passed; 65 full-suite tests passed with 6 intentional skips.
- **Next:** Phase 4.3 JWT login; later complete ownership enforcement, Google OAuth, Gradio integration, evaluation, CI/CD and Hugging Face deployment.
