
-- Migration 007: Temporary, session-scoped insurance documents.
--
-- Existing documents remain unchanged. In particular, legacy
-- documents with NULL user_id are not assigned to any user.
--
-- Expiration controls access. Physical deletion from PostgreSQL
-- and ChromaDB will be implemented in the cleanup phase.

ALTER TABLE public.documents
ADD COLUMN session_id UUID,
ADD COLUMN last_activity_at TIMESTAMPTZ,
ADD COLUMN expires_at TIMESTAMPTZ;

ALTER TABLE public.documents
ADD CONSTRAINT documents_session_id_fkey
FOREIGN KEY (session_id)
REFERENCES public.user_sessions(session_id);

ALTER TABLE public.documents
ADD CONSTRAINT documents_temporary_ownership_check
CHECK (
    (user_id IS NULL AND session_id IS NULL)
    OR
    (user_id IS NOT NULL AND session_id IS NOT NULL)
);

ALTER TABLE public.documents
ADD CONSTRAINT documents_temporary_expiration_check
CHECK (
    (
        session_id IS NULL
        AND last_activity_at IS NULL
        AND expires_at IS NULL
    )
    OR
    (
        session_id IS NOT NULL
        AND last_activity_at IS NOT NULL
        AND expires_at IS NOT NULL
        AND expires_at > last_activity_at
    )
);

CREATE INDEX idx_documents_user_session
ON public.documents(user_id, session_id);

CREATE INDEX idx_documents_expires_at
ON public.documents(expires_at)
WHERE expires_at IS NOT NULL;
