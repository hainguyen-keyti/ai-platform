CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    email           TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    name            TEXT,
    role            TEXT NOT NULL DEFAULT 'user',
    quota_remaining INTEGER NOT NULL DEFAULT 100,
    -- The balance comes back up to quota_daily on the first request of each UTC
    -- day; last_refill_day is what makes that happen once.
    quota_daily     INTEGER NOT NULL DEFAULT 100,
    last_refill_day TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token      TEXT UNIQUE NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- provider_thread_url is where this conversation lives on the provider's own
-- site. One thread per conversation is what lets a later turn build on an
-- earlier one; it is never shared, because a conversation has one owner.
CREATE TABLE IF NOT EXISTS conversations (
    id                  TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider            TEXT NOT NULL,
    title               TEXT,
    provider_thread_url TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- filename is a bare name, not a path: the API container and the host worker
-- mount the same media directory at different roots and each joins its own.
CREATE TABLE IF NOT EXISTS media (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
    message_id      TEXT REFERENCES messages(id) ON DELETE SET NULL,
    provider        TEXT NOT NULL,
    type            TEXT NOT NULL,
    prompt          TEXT,
    filename        TEXT NOT NULL,
    metadata        TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- A claim takes a lease and bumps attempts. A worker that dies mid-job stops
-- renewing, the lease runs out, and the next claim sweeps the row back to
-- pending; a late result from the dead attempt is refused because its attempt
-- number no longer matches. That is what keeps a credit from being charged,
-- refunded or media attached twice.
CREATE TABLE IF NOT EXISTS jobs (
    id               TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id  TEXT REFERENCES conversations(id) ON DELETE SET NULL,
    provider         TEXT NOT NULL,
    feature          TEXT NOT NULL,
    payload          TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending',
    attempts         INTEGER NOT NULL DEFAULT 0,
    lease_expires_at TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    phase            TEXT,
    result           TEXT,
    error            TEXT,
    error_kind       TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    started_at       TEXT,
    finished_at      TEXT
);

-- A conversation deleted here still lives as a thread in the provider's
-- account. The worker holds no database, so the api leaves it this note; the
-- worker claims it, removes the thread and settles it, three tries at most.
CREATE TABLE IF NOT EXISTS thread_tombstones (
    id          TEXT PRIMARY KEY,
    provider    TEXT NOT NULL,
    thread_url  TEXT NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 0,
    claimed_at  TEXT,
    deleted_at  TEXT,
    error       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One row per provider a worker has asked for work on. A pending job is only
-- declared unserved when nobody has asked for that provider lately, so a job
-- queued behind a five minute picture is never mistaken for an orphan.
CREATE TABLE IF NOT EXISTS worker_pings (
    provider  TEXT PRIMARY KEY,
    last_seen TEXT NOT NULL DEFAULT (datetime('now')),
    -- What the worker last said of its picture budget; budget_free_at only while it is spent.
    images_3h      INTEGER,
    image_budget   INTEGER,
    budget_free_at TEXT
);

-- A provider whose account needs its admin (signed out, memory on) is held out until `until`: not
-- offered and no turn taken, since every turn would fail the same way until then.
CREATE TABLE IF NOT EXISTS provider_holds (
    provider TEXT PRIMARY KEY,
    until    TEXT NOT NULL,
    reason   TEXT
);

-- A person's key for programs calling /v1. Only its SHA-256 is kept: the key itself is shown once,
-- when it is made. A revoked key stays as a row so its id cannot be reused.
CREATE TABLE IF NOT EXISTS api_keys (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    prefix       TEXT NOT NULL,
    key_hash     TEXT UNIQUE NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT,
    revoked_at   TEXT
);

-- The conversation, and so the provider thread, every /v1 request of a key goes into, per provider, for
-- one UTC day (issue #26). A new day, or a conversation the person deleted, starts a new one.
CREATE TABLE IF NOT EXISTS api_key_conversations (
    key_id          TEXT NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    provider        TEXT NOT NULL,
    day             TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    PRIMARY KEY (key_id, provider)
);

-- The conversation a named session of a key keeps on a provider, across days (issue #28): a character
-- of its own, unseen by the key's other sessions. A conversation the person deleted starts a new one.
CREATE TABLE IF NOT EXISTS api_key_sessions (
    key_id          TEXT NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    provider        TEXT NOT NULL,
    name            TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (key_id, provider, name)
);

CREATE INDEX IF NOT EXISTS idx_tombstones_open      ON thread_tombstones(deleted_at, claimed_at, created_at);
CREATE INDEX IF NOT EXISTS idx_sessions_token       ON sessions(token);
CREATE INDEX IF NOT EXISTS idx_conversations_user   ON conversations(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_conv        ON messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_media_user           ON media(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_claim           ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_user            ON jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_user        ON api_keys(user_id, revoked_at);
