
-- Migration 006: Retain consumed refresh-token hashes.
--
-- Migration 005 must remain unchanged because its checksum
-- has already been recorded by the migration runner.
--
-- The history table supports future refresh-token replay detection.
-- Plaintext refresh tokens must never be stored here.

CREATE TABLE public.refresh_token_history (
    token_hash CHAR(64) PRIMARY KEY,

    session_id UUID NOT NULL
        REFERENCES public.user_sessions(session_id)
        ON DELETE CASCADE,

    consumed_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP
);

-- Find consumed tokens belonging to a particular session.
CREATE INDEX idx_refresh_token_history_session_id
ON public.refresh_token_history (session_id);

-- Application-role permissions for session persistence.
-- Schema migrations are executed using the migration owner.
-- Application code connects using the restricted app role.

GRANT SELECT, INSERT, UPDATE
ON public.user_sessions
TO health_rag_app;

GRANT SELECT, INSERT
ON public.refresh_token_history
TO health_rag_app;
