-- Customer Loyalty Rewards System: SQLite schema
CREATE TABLE IF NOT EXISTS users (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  email           TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name            TEXT NOT NULL,
  password_hash   TEXT NOT NULL,
  role            TEXT NOT NULL DEFAULT 'customer' CHECK (role IN ('customer','admin')),
  points_balance  INTEGER NOT NULL DEFAULT 0 CHECK (points_balance >= 0),
  lifetime_points INTEGER NOT NULL DEFAULT 0,
  blocked         INTEGER NOT NULL DEFAULT 0,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS products (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  sku     TEXT NOT NULL UNIQUE,
  name    TEXT NOT NULL,
  points  INTEGER NOT NULL CHECK (points > 0),
  active  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS batches (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id  INTEGER NOT NULL REFERENCES products(id),
  quantity    INTEGER NOT NULL CHECK (quantity > 0),
  status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','voided')),
  note        TEXT NOT NULL DEFAULT '',
  created_by  INTEGER REFERENCES users(id),
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Only the HMAC hash of each code is stored; the plain code exists only on the printed box.
CREATE TABLE IF NOT EXISTS codes (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id     INTEGER NOT NULL REFERENCES batches(id),
  serial       TEXT NOT NULL UNIQUE,
  code_hash    TEXT NOT NULL UNIQUE,
  status       TEXT NOT NULL DEFAULT 'unused' CHECK (status IN ('unused','redeemed','voided')),
  redeemed_by  INTEGER REFERENCES users(id),
  redeemed_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_codes_batch ON codes(batch_id);

CREATE TABLE IF NOT EXISTS ledger (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER NOT NULL REFERENCES users(id),
  delta       INTEGER NOT NULL,
  reason      TEXT NOT NULL,
  ref         TEXT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ledger_user ON ledger(user_id);

CREATE TABLE IF NOT EXISTS rewards (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  name         TEXT NOT NULL,
  description  TEXT NOT NULL DEFAULT '',
  cost         INTEGER NOT NULL CHECK (cost > 0),
  stock        INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
  active       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS claims (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER NOT NULL REFERENCES users(id),
  reward_id   INTEGER NOT NULL REFERENCES rewards(id),
  cost        INTEGER NOT NULL,
  status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','fulfilled','rejected')),
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Every code / login attempt, used for rate limiting and fraud alerts.
CREATE TABLE IF NOT EXISTS attempts (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER REFERENCES users(id),
  ip          TEXT,
  outcome     TEXT NOT NULL,   -- success | invalid | reused | voided | rate_limited | login_failed
  code_hash   TEXT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_attempts_time ON attempts(created_at);

CREATE TABLE IF NOT EXISTS audit (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  actor_id    INTEGER REFERENCES users(id),
  action      TEXT NOT NULL,
  detail      TEXT NOT NULL DEFAULT '',
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
