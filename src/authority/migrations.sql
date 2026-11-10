-- Migration 001: Authority schema
-- SQLite, WAL mode, foreign keys enabled, synchronous=FULL.
-- One project knowledge service on a single machine.

-- Projects: one row per project, with a restore epoch and monotonic commit sequence.
CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    epoch       TEXT NOT NULL,
    sequence    INTEGER NOT NULL DEFAULT 0
);

-- Page heads: the current (or retired) revision per page within a project.
CREATE TABLE IF NOT EXISTS page_heads (
    project     TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    page        TEXT NOT NULL,
    revision    TEXT NOT NULL,
    state       TEXT NOT NULL CHECK(state IN ('active', 'retired')),
    PRIMARY KEY (project, page)
);

-- Page revisions: immutable body, title, links, evidence citations, predecessor.
-- Never modified after insertion.
CREATE TABLE IF NOT EXISTS page_revisions (
    revision        TEXT PRIMARY KEY,
    project         TEXT NOT NULL REFERENCES projects(id),
    page            TEXT NOT NULL,
    base_revision   TEXT REFERENCES page_revisions(revision),
    title           TEXT NOT NULL,
    body            TEXT NOT NULL,
    links           TEXT DEFAULT '[]',
    citations       TEXT DEFAULT '[]',
    state           TEXT NOT NULL CHECK(state IN ('active', 'retired')),
    review_identity TEXT
);

-- Project heads: maps project to its current commit sequence.
CREATE TABLE IF NOT EXISTS project_heads (
    project  TEXT PRIMARY KEY REFERENCES projects(id),
    revision TEXT NOT NULL REFERENCES page_revisions(revision)
);

-- Proposals: immutable proposed changes with actor identity, base revision,
-- source references, and payload digest.
CREATE TABLE IF NOT EXISTS proposals (
    proposal_id   TEXT PRIMARY KEY,
    project       TEXT NOT NULL REFERENCES projects(id),
    page          TEXT NOT NULL,
    base_revision TEXT NOT NULL REFERENCES page_revisions(revision),
    change_kind   TEXT NOT NULL CHECK(change_kind IN ('create', 'replace', 'retire')),
    change_body   TEXT NOT NULL,
    title         TEXT NOT NULL,
    actor         TEXT NOT NULL,
    sources       TEXT DEFAULT '[]',
    payload_digest TEXT NOT NULL,
    state         TEXT NOT NULL CHECK(state IN ('pending', 'blocked', 'decided')),
    decision_kind TEXT,
    decision_json TEXT,
    rejected_reason TEXT
);

-- Idempotency keys: bind project+principal+request to one proposal.
CREATE TABLE IF NOT EXISTS proposal_keys (
    key           TEXT PRIMARY KEY,
    proposal_id   TEXT NOT NULL UNIQUE REFERENCES proposals(proposal_id) ON DELETE CASCADE,
    project       TEXT NOT NULL REFERENCES projects(id),
    page          TEXT NOT NULL,
    base_revision TEXT NOT NULL REFERENCES page_revisions(revision)
);

-- Decisions: immutable review outcomes bound to an exact proposal digest.
CREATE TABLE IF NOT EXISTS decisions (
    proposal_id    TEXT PRIMARY KEY REFERENCES proposals(proposal_id) ON DELETE CASCADE,
    decision_kind  TEXT NOT NULL CHECK(decision_kind IN ('publish', 'reject')),
    decision_json  TEXT NOT NULL,
    review_digest  TEXT
);

-- Operations: bind project, authenticated principal, and idempotency key
-- to the request digest and durable result.
CREATE TABLE IF NOT EXISTS operations (
    op_key          TEXT PRIMARY KEY,
    project         TEXT NOT NULL REFERENCES projects(id),
    principal       TEXT NOT NULL,
    request_digest  TEXT NOT NULL,
    result_digest   TEXT NOT NULL,
    status          TEXT NOT NULL CHECK(status IN ('submitted', 'committed', 'failed')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Transactional FTS5 table for full-text search (within the authority transaction).
CREATE TABLE IF NOT EXISTS fts_pages (
    project TEXT,
    page    TEXT,
    revision TEXT,
    body    TEXT,
    state   TEXT CHECK(state IN ('indexed', 'pending'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS fts_pages_fts USING fts5(
    project, page, revision, body,
    content=fts_pages,
    content_rowid=revision
);

-- Outbox: durable index/export queue.
CREATE TABLE IF NOT EXISTS outbox (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project     TEXT NOT NULL REFERENCES projects(id),
    page        TEXT NOT NULL,
    revision    TEXT NOT NULL REFERENCES page_revisions(revision),
    kind        TEXT NOT NULL CHECK(kind IN ('index', 'export')),
    status      TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'done', 'failed')),
    error       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Evidence revisions: captured UTF-8 text, its hash and provenance.
-- Mutable URLs are locators, not evidence identities.
CREATE TABLE IF NOT EXISTS evidence_revisions (
    revision  TEXT PRIMARY KEY,
    project   TEXT NOT NULL REFERENCES projects(id),
    title     TEXT NOT NULL,
    text      TEXT NOT NULL,
    locator   TEXT NOT NULL,
    hash      TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Index state: tracks generation and indexed-through revision.
CREATE TABLE IF NOT EXISTS index_state (
    project    TEXT PRIMARY KEY REFERENCES projects(id),
    generation TEXT NOT NULL,
    indexed_through TEXT NOT NULL REFERENCES page_revisions(revision),
    model_digest TEXT NOT NULL
);
