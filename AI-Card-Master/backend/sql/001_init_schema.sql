-- Initial PostgreSQL schema for AI-Card-Master.
-- Security notes:
-- 1) UUID primary keys are generated in DB via pgcrypto/gen_random_uuid().
-- 2) Emails are unique and indexed.
-- 3) Foreign key uses ON DELETE CASCADE to avoid orphan generations.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_type
        WHERE typname = 'subscription_status_enum'
    ) THEN
        CREATE TYPE subscription_status_enum AS ENUM ('Free', 'Pro');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(320) NOT NULL UNIQUE,
    hashed_password VARCHAR(1024) NOT NULL,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    subscription_status subscription_status_enum NOT NULL DEFAULT 'Free'
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS ix_users_email ON users (email);
CREATE INDEX IF NOT EXISTS ix_users_is_admin ON users (is_admin);

CREATE TABLE IF NOT EXISTS generations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    input_image_url VARCHAR(2048) NOT NULL,
    result_image_url VARCHAR(2048) NOT NULL,
    prompt_used TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_generations_user_id ON generations (user_id);
CREATE INDEX IF NOT EXISTS ix_generations_created_at ON generations (created_at);

CREATE TABLE IF NOT EXISTS generation_error_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    source VARCHAR(128) NOT NULL,
    error_message TEXT NOT NULL,
    context JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_generation_error_logs_user_id ON generation_error_logs (user_id);
CREATE INDEX IF NOT EXISTS ix_generation_error_logs_source ON generation_error_logs (source);
CREATE INDEX IF NOT EXISTS ix_generation_error_logs_created_at ON generation_error_logs (created_at);
