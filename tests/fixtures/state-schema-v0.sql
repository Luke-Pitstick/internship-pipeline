-- Frozen state schema from e8598fa685aca8c31d906de8faac3270812783cd (v1.0.1 RC).
-- Keep this historical fixture unchanged when adding migrations.

CREATE TABLE IF NOT EXISTS targets (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, config TEXT NOT NULL, provider TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1, baselined INTEGER NOT NULL DEFAULT 0,
    next_due REAL NOT NULL DEFAULT 0, lease_until REAL NOT NULL DEFAULT 0,
    last_success REAL, last_attempt REAL, failures INTEGER NOT NULL DEFAULT 0,
    error TEXT, complete INTEGER NOT NULL DEFAULT 0,
    collection_owner TEXT NOT NULL DEFAULT 'registry'
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, data TEXT NOT NULL, canonical_url TEXT NOT NULL,
    company_key TEXT NOT NULL, requisition_id TEXT, content_hash TEXT NOT NULL,
    status TEXT NOT NULL, first_seen REAL NOT NULL, last_seen REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_url ON jobs(canonical_url, company_key);
CREATE INDEX IF NOT EXISTS jobs_requisition ON jobs(company_key, requisition_id);
CREATE TABLE IF NOT EXISTS observations (
    source TEXT NOT NULL, board_id TEXT NOT NULL, source_id TEXT NOT NULL,
    target_id TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES jobs(id),
    last_seen REAL NOT NULL, misses INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(source, board_id, source_id)
);
CREATE TABLE IF NOT EXISTS matches (
    job_id TEXT NOT NULL REFERENCES jobs(id), content_hash TEXT NOT NULL,
    profile_revision TEXT NOT NULL, result TEXT NOT NULL, created REAL NOT NULL,
    PRIMARY KEY(job_id, content_hash, profile_revision)
);
CREATE TABLE IF NOT EXISTS assessments (
    identity TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
    result TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS assessment_attempts (
    id INTEGER PRIMARY KEY, identity TEXT NOT NULL, job_id TEXT NOT NULL,
    started REAL NOT NULL, completed REAL, status TEXT NOT NULL,
    reserved_tokens INTEGER NOT NULL, input_tokens INTEGER, output_tokens INTEGER
);
CREATE INDEX IF NOT EXISTS assessment_attempt_identity ON assessment_attempts(identity);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, key TEXT NOT NULL UNIQUE,
    payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0, available_at REAL NOT NULL,
    lease_until REAL, token TEXT, error TEXT, created REAL NOT NULL, updated REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS task_claim ON tasks(kind, status, available_at);
CREATE TABLE IF NOT EXISTS providers (
    id TEXT PRIMARY KEY, next_allowed REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS candidates (
    url TEXT PRIMARY KEY, company TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
    error TEXT, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS maintenance (
    name TEXT PRIMARY KEY, next_due REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, job_id TEXT,
    at REAL NOT NULL, details TEXT NOT NULL DEFAULT '{}'
);
