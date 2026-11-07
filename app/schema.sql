-- Customer Loyalty Rewards System: database schema (SQLite)
-- Timestamps are UTC text: 'YYYY-MM-DD HH:MM:SS'

CREATE TABLE IF NOT EXISTS admins (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    email          TEXT NOT NULL UNIQUE,
    name           TEXT NOT NULL,
    password_hash  TEXT NOT NULL,
    points_balance INTEGER NOT NULL DEFAULT 0 CHECK (points_balance >= 0),
    status         TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended')),
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    sku        TEXT NOT NULL UNIQUE,
    points     INTEGER NOT NULL CHECK (points > 0),
    active     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

-- A batch = one print run of codes for one product.
CREATE TABLE IF NOT EXISTS batches (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity   INTEGER NOT NULL CHECK (quantity > 0),
    status     TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','voided')),
    note       TEXT,
    expires_at TEXT,
    created_by INTEGER REFERENCES admins(id),
    created_at TEXT NOT NULL
);

-- Only an HMAC hash of each code is stored, never the code itself.
CREATE TABLE IF NOT EXISTS codes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id    INTEGER NOT NULL REFERENCES batches(id),
    code_hash   TEXT NOT NULL UNIQUE,
    status      TEXT NOT NULL DEFAULT 'unused' CHECK (status IN ('unused','redeemed','voided')),
    redeemed_by INTEGER REFERENCES customers(id),
    redeemed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_codes_batch ON codes(batch_id, status);

-- Append-only record of every point movement. Balance can be re-derived from it.
CREATE TABLE IF NOT EXISTS point_ledger (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    delta       INTEGER NOT NULL,
    reason      TEXT NOT NULL CHECK (reason IN ('code_redeem','reward_claim','claim_refund')),
    ref_id      INTEGER,
    note        TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ledger_customer ON point_ledger(customer_id, id);

CREATE TABLE IF NOT EXISTS rewards (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    points_cost INTEGER NOT NULL CHECK (points_cost > 0),
    stock       INTEGER CHECK (stock IS NULL OR stock >= 0),   -- NULL = unlimited
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claims (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    reward_id   INTEGER NOT NULL REFERENCES rewards(id),
    points_spent INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','fulfilled','cancelled')),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(status, id);

-- Audit/fraud log: redemption outcomes and failed logins.
CREATE TABLE IF NOT EXISTS security_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,
    customer_id INTEGER REFERENCES customers(id),
    ip          TEXT,
    detail      TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_kind_time ON security_events(kind, created_at);
CREATE INDEX IF NOT EXISTS idx_events_customer ON security_events(customer_id, created_at);
CREATE INDEX IF NOT EXISTS idx_events_ip ON security_events(ip, created_at);
