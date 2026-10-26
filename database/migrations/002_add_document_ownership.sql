-- Migration 002: Add document ownership.
-- Keep user_id nullable temporarily to preserve legacy documents.

ALTER TABLE public.documents
ADD COLUMN user_id UUID;

ALTER TABLE public.documents
ADD CONSTRAINT documents_user_id_fkey
FOREIGN KEY (user_id)
REFERENCES public.users(user_id);

CREATE INDEX idx_documents_user_id
ON public.documents(user_id);