
-- Migration 005: Create persistent authentication sessions.
--
-- Each row represents one login session belonging to a user.
-- Refresh tokens are never stored in plaintext.
-- The application stores only a SHA-256 token digest.
--
-- The table supports:
--   - Multiple login sessions per user
--   - Refresh-token rotation
--   - Session expiration
--   - Session revocation during logout
--   - Detection of reused refresh tokens

CREATE TABLE public.user_sessions (
    session_id UUID PRIMARY KEY,

    user_id UUID NOT NULL
        REFERENCES public.users(user_id)
        ON DELETE CASCADE,

    refresh_token_hash CHAR(64) NOT NULL,

    created_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    rotated_at TIMESTAMPTZ,

    expires_at TIMESTAMPTZ NOT NULL,

    revoked_at TIMESTAMPTZ,

    CONSTRAINT user_sessions_valid_expiry
        CHECK (expires_at > created_at),

    CONSTRAINT user_sessions_unique_refresh_hash
        UNIQUE (refresh_token_hash)
);

-- Efficiently retrieve sessions belonging to a user.
CREATE INDEX idx_user_sessions_user_id
ON public.user_sessions (user_id);

-- Support cleanup of expired sessions.
CREATE INDEX idx_user_sessions_expires_at
ON public.user_sessions (expires_at);
