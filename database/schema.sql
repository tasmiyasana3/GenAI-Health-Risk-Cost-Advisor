-- Original document registry schema (Phase 3).
-- Use only for initializing a new, empty test database.
-- Do not run against the existing health_rag_db database.

CREATE TABLE public.documents (
    document_id VARCHAR(32) PRIMARY KEY,
    filename TEXT NOT NULL,
    collection_name TEXT NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'processing',
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT valid_document_status
        CHECK (status IN ('processing', 'ready', 'failed'))
);