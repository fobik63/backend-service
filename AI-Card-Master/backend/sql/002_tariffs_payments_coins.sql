-- Billing extension: AI-coins, subscription expiry, payments (mirrors 20260806_0002)

ALTER TYPE subscription_status_enum ADD VALUE IF NOT EXISTS 'Start';
ALTER TYPE subscription_status_enum ADD VALUE IF NOT EXISTS 'HalfYear';
ALTER TYPE subscription_status_enum ADD VALUE IF NOT EXISTS 'Year';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tariff_code_enum') THEN
        CREATE TYPE tariff_code_enum AS ENUM ('start', 'pro', 'half_year', 'year');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'payment_status_enum') THEN
        CREATE TYPE payment_status_enum AS ENUM (
            'pending',
            'waiting_for_capture',
            'succeeded',
            'canceled',
            'failed'
        );
    END IF;
END $$;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS ai_coins INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS subscription_ends_at TIMESTAMPTZ NULL;

CREATE INDEX IF NOT EXISTS ix_users_subscription_ends_at ON users (subscription_ends_at);

CREATE TABLE IF NOT EXISTS payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tariff_code tariff_code_enum NOT NULL,
    yookassa_payment_id VARCHAR(128) NOT NULL UNIQUE,
    amount_rub NUMERIC(10, 2) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'RUB',
    status payment_status_enum NOT NULL DEFAULT 'pending',
    confirmation_url VARCHAR(2048) NULL,
    description VARCHAR(512) NULL,
    raw_webhook_payload TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS ix_payments_user_id ON payments (user_id);
CREATE INDEX IF NOT EXISTS ix_payments_tariff_code ON payments (tariff_code);
CREATE INDEX IF NOT EXISTS ix_payments_yookassa_payment_id ON payments (yookassa_payment_id);
CREATE INDEX IF NOT EXISTS ix_payments_status ON payments (status);
CREATE INDEX IF NOT EXISTS ix_payments_created_at ON payments (created_at);
