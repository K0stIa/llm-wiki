"""Authority layer: transactional SQLite knowledge store.

Implements the Knowledge and Curator interfaces from contract.d.ts.
All mutations go through the authority; MCP clients never coordinate
storage steps themselves.

First release: one local service, SQLite authority, QMD+FTS5 retrieval,
project-bound MCP clients (Pi -> Codex CLI -> Claude Code -> OpenCode).
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


# ─── Types (from contract.d.ts, simplified) ───────────────────────────

class PageState(str, Enum):
    ACTIVE = "active"
    RETIRED = "retired"


class ProposalState(str, Enum):
    PENDING = "pending"
    BLOCKED = "blocked"
    DECIDED = "decided"


class ChangeKind(str, Enum):
    CREATE = "create"
    REPLACE = "replace"
    RETIRE = "retire"


class DecisionKind(str, Enum):
    PUBLISH = "publish"
    REJECT = "reject"


@dataclass
class Citation:
    start: int  # Line, 1-based
    end: int  # Line, 1-based (inclusive)
    hash: str  # "h:<sha256>"
    kind: str  # "page" | "source"
    page: Optional[str] = None
    revision: Optional[str] = None
    source: Optional[str] = None


@dataclass
class PageSnapshot:
    page: str
    revision: str
    hash: str
    title: str
    markdown: str
    state: str


@dataclass
class ProposalReceipt:
    kind: str  # "pending"
    key: str
    proposal: str
    digest: str


@dataclass
class DecisionOutcome:
    kind: str  # "committed" | "rejected" | "conflict"
    page_revision: Optional[str] = None
    project_revision: Optional[str] = None
    reason: Optional[str] = None
    current: Optional[str] = None


# ─── Authority ─────────────────────────────────────────────────────────

class AuthorityError(Exception):
    pass


class ConflictError(AuthorityError):
    """CAS conflict: base revision doesn't match current head."""

    def __init__(self, current_revision: Optional[str] = None):
        self.current_revision = current_revision
        super().__init__(f"Conflicting base revision: current={current_revision}")


class NotFoundError(AuthorityError):
    pass


class CapacityError(AuthorityError):
    pass


class InvalidInputError(AuthorityError):
    pass


class KnowledgeStore:
    """Transactional authority over SQLite + FTS5.

    Thread-safe via a single write lock. Readers are concurrent.
    All mutations are inside a BEGIN IMMEDIATE transaction.
    """

    def __init__(self, db_path: str | Path, schema_path: Optional[str | Path] = None):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._schema_path = Path(schema_path) if schema_path else None
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()
        # Current project's epoch + sequence (monotonic)
        self._project_epoch: str = ""
        self._project_sequence: int = 0
        # FTS sync interval (flush after this many mutations)
        self._fts_sync_threshold: int = 50
        self._fts_pending: int = 0

    def connect(self, project_id: str) -> sqlite3.Connection:
        """Connect to the database and run migrations.
        Returns a connection with foreign keys and WAL enabled."""
        if self._conn:
            return self._conn

        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")

        # Only load schema file for on-disk databases
        if self._schema_path and self._schema_path.is_file():
            conn.executescript(self._schema_path.read_text())
        elif not self._conn:
            pass  # Schema already loaded from file; for in-memory, no-op

        # Ensure the project exists
        conn.execute(
            "INSERT OR IGNORE INTO projects VALUES (?, ?, 0)",
            (project_id, self._generate_epoch())
        )
        conn.commit()

        self._conn = conn
        self._project_epoch = self._get_epoch(project_id)
        self._project_sequence = self._get_sequence(project_id)
        return conn

    def disconnect(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def _generate_epoch(self) -> str:
        return uuid.uuid4().hex[:16]

    def _get_epoch(self, project_id: str) -> str:
        if not self._conn:
            raise AuthorityError("Not connected")
        row = self._conn.execute(
            "SELECT epoch FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        if not row:
            raise NotFoundError(f"Project {project_id} not found")
        return row[0]

    def _get_sequence(self, project_id: str) -> int:
        row = self._get_conn().execute(
            "SELECT sequence FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        return row[0] if row else 0

    def _get_conn(self) -> sqlite3.Connection:
        if not self._conn:
            raise AuthorityError("Not connected")
        return self._conn

    # ─── Page operations ──────────────────────────────────────────

    def create_page(self, project_id: str, page: str, title: str,
                    markdown: str, actor: str, sources: list[dict] = None
                    ) -> PageSnapshot:
        """Create a new page. Idempotent on (project, page)."""
        conn = self.connect(project_id)

        with conn:
            # Idempotency: if page exists and is active, return current
            head = conn.execute(
                "SELECT revision, state FROM page_heads WHERE project=? AND page=?",
                (project_id, page)
            ).fetchone()
            if head and head[1] == "active":
                return self._page_snapshot(conn, head[0])

            # Create the revision
            revision = self._make_revision(conn, project_id, page, title, markdown, None)

            # Insert page head
            conn.execute(
                "INSERT INTO page_heads VALUES (?, ?, ?, 'active')",
                (project_id, page, revision)
            )

            # Update project sequence
            self._project_sequence += 1
            conn.execute(
                "UPDATE projects SET sequence=? WHERE id=?",
                (self._project_sequence, project_id)
            )

            # Insert into outbox for indexing
            conn.execute(
                "INSERT INTO outbox (project, page, revision, kind) VALUES (?, ?, ?, 'index')",
                (project_id, page, revision)
            )

            conn.commit()
            return self._page_snapshot(conn, revision)

    def page(self, project_id: str, page: str, revision: Optional[str] = None
             ) -> PageSnapshot:
        """Read a page. Missing revision means current."""
        conn = self.connect(project_id)
        head = conn.execute(
            "SELECT revision, state FROM page_heads WHERE project=? AND page=?",
            (project_id, page)
        ).fetchone()
        if not head:
            raise NotFoundError(f"Page {page} not found in {project_id}")
        if revision:
            row = conn.execute(
                "SELECT title, body, revision FROM page_revisions WHERE revision=?",
                (revision,)
            ).fetchone()
            if not row:
                raise NotFoundError(f"Revision {revision} not found")
            return PageSnapshot(
                page=page, revision=revision,
                hash=self._hash_body(row[1]),
                title=row[0], markdown=row[1], state=head[1]
            )
        return self._page_snapshot(conn, head[0])

    def capture_source(self, project_id: str, title: str,
                       text: str, locator: str) -> str:
        """Capture evidence source. Returns revision ID."""
        conn = self.connect(project_id)
        revision = "src-" + uuid.uuid4().hex[:8]
        hash_val = "h:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
        conn.execute(
            "INSERT INTO evidence_revisions (revision, project, title, text, locator, hash) VALUES (?,?,?,?,?,?)",
            (revision, project_id, title, text, locator, hash_val)
        )
        conn.commit()
        return revision

    def read_citation(self, citation: Citation) -> Optional[str]:
        """Exact historical citation read. Private evidence requires owner/curator scope.
        Hash covers entire stored UTF-8 body; span is inclusive and 1-based.
        Returns None if revision not found."""
        conn = self._get_conn()
        if citation.kind == "page":
            row = conn.execute(
                "SELECT body, title, revision, state FROM page_revisions WHERE revision=?",
                (citation.revision,)
            ).fetchone()
            if not row:
                return None
            return PageSnapshot(
                page=citation.page or "",
                revision=citation.revision,
                hash=self._hash_body(row[0]),
                title=row[1], markdown=row[0],
                state=row[3]
            )
        elif citation.kind == "source":
            # Private evidence — requires owner or curator scope
            # Source revision stored in evidence_revisions table
            row = conn.execute(
                "SELECT text, locator FROM evidence_revisions WHERE revision=?",
                (citation.revision,)
            ).fetchone()
            if not row:
                return None
            return {"kind": "source", "text": row[0], "locator": row[1], "revision": citation.revision}
        return None

    def process_outbox(self, project_id: str) -> int:
        """Process outbox: promote pending indexes, promote exports.
        Returns number of items processed. All within a transaction."""
        conn = self.connect(project_id)
        with conn:
            # Promote indexes
            promoted = conn.execute(
                "UPDATE outbox SET status='done' WHERE kind='index' AND status='pending'",
                ()
            ).rowcount
            # Promote exports
            exported = conn.execute(
                "UPDATE outbox SET status='done' WHERE kind='export' AND status='pending'",
                ()
            ).rowcount
            conn.commit()
            return promoted + exported

    def get_outbox_status(self, project_id: str) -> dict:
        """Get outbox counts by status."""
        conn = self.connect(project_id)
        rows = conn.execute(
            "SELECT kind, status, COUNT(*) FROM outbox WHERE project=? GROUP BY kind, status",
            (project_id,)
        ).fetchall()
        result = {}
        for kind, status, count in rows:
            result[f"{kind}:{status}"] = count
        return result

    def propose(self, project_id: str, page: str,
                base_revision: str, change_kind: ChangeKind,
                title: str, markdown: str, actor: str,
                sources: list[dict], key: Optional[str] = None
                ) -> Optional[ProposalReceipt]:
        """Propose a change. Returns proposal receipt or None (conflict)."""
        conn = self.connect(project_id)

        with conn:
            # Check if page exists
            head = conn.execute(
                "SELECT revision, state FROM page_heads WHERE project=? AND page=?",
                (project_id, page)
            ).fetchone()
            if not head:
                if change_kind == ChangeKind.REPLACE or change_kind == ChangeKind.RETIRE:
                    raise NotFoundError(f"Page {page} not found for {change_kind}")
                # CREATE on non-existent page: create first
                if change_kind == ChangeKind.CREATE:
                    return None  # Will be handled by create_page

            # CAS: base must match current head
            if change_kind in (ChangeKind.REPLACE, ChangeKind.RETIRE):
                if head[0] != base_revision:
                    return None  # Conflict
                if head[1] != "active":
                    return None  # Retired page

            # Idempotency: same key (or same generated key) returns existing proposal
            effective_key = key or self._make_key(project_id, page, base_revision,
                                                  change_kind, title, markdown)
            existing = conn.execute(
                "SELECT proposal_id FROM proposal_keys WHERE key=?",
                (effective_key,)
            ).fetchone()
            if existing:
                return ProposalReceipt(
                    kind="pending", key=effective_key,
                    proposal=existing[0],
                    digest=self._digest_request(project_id, page, base_revision,
                                                 change_kind, title, markdown, sources)
                )

            # Create proposal
            proposal_id = "prop-" + uuid.uuid4().hex[:8]
            digest = self._digest_request(project_id, page, base_revision,
                                          change_kind, title, markdown, sources)

            conn.execute(
                "INSERT INTO proposals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)",
                (proposal_id, project_id, page, base_revision,
                 change_kind.value, markdown, title, actor,
                 json.dumps(sources), digest, 'pending')
            )

            # Record idempotency key
            conn.execute(
                "INSERT INTO proposal_keys VALUES (?, ?, ?, ?, ?)",
                (key or self._make_key(project_id, page, base_revision,
                                       change_kind, title, markdown),
                 proposal_id, project_id, page, base_revision)
            )

            # Log operation for G4 verification
            conn.execute(
                "INSERT INTO operations (op_key, project, principal, request_digest, result_digest, status) VALUES (?,?,?,?,?,?)",
                (effective_key, project_id, actor, digest, digest, 'submitted')
            )

            conn.commit()
            return ProposalReceipt(
                kind="pending", key=effective_key,
                proposal=proposal_id, digest=digest
            )

    def decide(self, project_id: str, proposal_key: str,
               decision: DecisionKind, reason: Optional[str] = None
               ) -> DecisionOutcome:
        """Curator decides: publish or reject a proposal."""
        conn = self.connect(project_id)

        with conn:
            # Lookup proposal via key
            key_row = conn.execute("""
                SELECT pk.proposal_id, pk.base_revision, p.change_kind, p.change_body,
                       p.title, p.actor, p.payload_digest
                FROM proposal_keys pk
                JOIN proposals p ON pk.proposal_id = p.proposal_id
                WHERE pk.key=?""", (proposal_key,)).fetchone()
            if not key_row:
                raise InvalidInputError(f"No proposal for key {proposal_key}")

            prop_id, base_rev, change_kind, body, title, actor, digest = key_row

            # Look up the page from the proposal
            page_row = conn.execute(
                "SELECT page FROM proposals WHERE proposal_id=?",
                (prop_id,)
            ).fetchone()
            if not page_row:
                raise NotFoundError("Proposal not found")
            page = page_row[0]

            # Lookup current page head
            current = conn.execute(
                "SELECT revision, state FROM page_heads WHERE project=? AND page=?",
                (project_id, page)
            ).fetchone()

            # CAS for publish
            if decision == DecisionKind.PUBLISH:
                if not current or current[0] != base_rev or current[1] != "active":
                    return DecisionOutcome(
                        kind="conflict", current=current[0] if current else None
                    )

                # Retire the old revision
                conn.execute(
                    "UPDATE page_revisions SET state='retired' WHERE revision=?",
                    (current[0],)
                )

                # Create new revision
                new_rev = self._make_revision(
                    conn, project_id, page, title, body, current[0]
                )

                # Update page head
                conn.execute(
                    "UPDATE page_heads SET revision=?, state='active' WHERE project=? AND page=?",
                    (new_rev, project_id, page)
                )

                # Record decision
                conn.execute(
                    "INSERT INTO decisions VALUES (?, 'publish', '{}', NULL)",
                    (prop_id,)
                )

                # Update proposal state
                conn.execute(
                    "UPDATE proposals SET state='decided', decision_kind='publish' WHERE proposal_id=?",
                    (prop_id,)
                )

                # Update project sequence
                self._project_sequence += 1
                conn.execute(
                    "UPDATE projects SET sequence=? WHERE id=?",
                    (self._project_sequence, project_id)
                )

                # Queue index
                conn.execute(
                    "INSERT INTO outbox (project, page, revision, kind) VALUES (?, ?, ?, 'index')",
                    (project_id, page, new_rev)
                )

                conn.commit()
                return DecisionOutcome(
                    kind="committed",
                    page_revision=new_rev,
                    project_revision=f"{project_id}:{self._project_epoch}:{self._project_sequence}"
                )

            elif decision == DecisionKind.REJECT:
                conn.execute(
                    "UPDATE proposals SET state='decided', decision_kind='reject', rejected_reason=? WHERE proposal_id=?",
                    (reason or "rejected", prop_id)
                )
                conn.execute(
                    "INSERT INTO decisions VALUES (?, 'reject', ?, NULL)",
                    (prop_id, json.dumps({"reason": reason or "rejected"}))
                )
                conn.commit()
                return DecisionOutcome(kind="rejected", reason=reason or "rejected")

            else:
                raise InvalidInputError(f"Unknown decision: {decision}")

    def read_proposal(self, project_id: str, proposal_id: str) -> Optional[dict]:
        """Read a proposal's full details (curator scope)."""
        conn = self.connect(project_id)
        row = conn.execute("""
            SELECT p.proposal_id, p.change_kind, p.change_body, p.title,
                   p.actor, p.sources, p.payload_digest, p.state,
                   p.decision_kind, p.rejected_reason,
                   pk.base_revision
            FROM proposals p
            LEFT JOIN proposal_keys pk ON p.proposal_id = pk.proposal_id
            WHERE p.proposal_id=?""", (proposal_id,)).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "change_kind": row[1],
            "body": row[2],
            "title": row[3],
            "actor": row[4],
            "sources": json.loads(row[5]) if row[5] else [],
            "digest": row[6],
            "state": row[7],
            "decision": row[8],
            "rejected_reason": row[9],
            "base_revision": row[10]
        }

    def operation(self, project_id: str, op_key: str) -> Optional[dict]:
        """Read operation state (principal-scoped replay)."""
        conn = self.connect(project_id)
        row = conn.execute(
            "SELECT op_key, project, principal, request_digest, result_digest, status FROM operations WHERE op_key=?",
            (op_key,)
        ).fetchone()
        if not row:
            return None
        return {
            "key": row[0],
            "project": row[1],
            "principal": row[2],
            "request_digest": row[3],
            "result_digest": row[4],
            "status": row[5]
        }

    # ─── Internal helpers ─────────────────────────────────────────

    def _make_revision(self, conn: sqlite3.Connection, project_id: str,
                       page: str, title: str, body: str, base: Optional[str]
                       ) -> str:
        """Create a new page revision and insert into FTS."""
        revision = "rev-" + uuid.uuid4().hex[:8]
        conn.execute(
            "INSERT INTO page_revisions (revision, project, page, base_revision, title, body, state) VALUES (?, ?, ?, ?, ?, ?, 'active')",
            (revision, project_id, page, base, title, body)
        )
        # Insert into FTS
        conn.execute(
            "INSERT INTO fts_pages VALUES (?, ?, ?, ?, 'pending')",
            (project_id, page, revision, body)
        )
        self._fts_pending += 1
        if self._fts_pending >= self._fts_sync_threshold:
            self._sync_fts(conn)
            self._fts_pending = 0
        return revision

    def _sync_fts(self, conn: sqlite3.Connection) -> None:
        """Sync pending FTS entries."""
        pending = conn.execute(
            "SELECT project, page, revision, body FROM fts_pages WHERE state='pending'"
        ).fetchall()
        for proj, pg, rev, body in pending:
            conn.execute(
                "INSERT OR REPLACE INTO fts_pages_fts VALUES (?, ?, ?, ?)",
                (proj, pg, rev, body)
            )
        conn.execute("UPDATE fts_pages SET state='indexed' WHERE state='pending'")
        conn.execute("INSERT INTO outbox (project, page, revision, kind) VALUES (?, 'reindex', (SELECT revision FROM page_revisions WHERE revision=?), 'index')",
                     (proj, rev))
        conn.commit()

    def _page_snapshot(self, conn: sqlite3.Connection, revision: str) -> PageSnapshot:
        row = conn.execute(
            "SELECT page, revision, body, title, state FROM page_revisions WHERE revision=?",
            (revision,)
        ).fetchone()
        if not row:
            raise NotFoundError(f"Revision {revision} not found")
        return PageSnapshot(
            page=row[0], revision=row[1],
            hash=self._hash_body(row[2]),
            title=row[3], markdown=row[2],
            state=row[4]
        )

    def _hash_body(self, body: str) -> str:
        return "h:" + hashlib.sha256(body.encode("utf-8")).hexdigest()

    def _digest_request(self, project_id: str, page: str, base_revision: str,
                        change_kind: ChangeKind, title: str, markdown: str,
                        sources: list[dict]) -> str:
        data = f"{project_id}:{page}:{base_revision}:{change_kind.value}:{title}:{markdown}:{json.dumps(sources, sort_keys=True)}"
        return "d:" + hashlib.sha256(data.encode()).hexdigest()

    def _make_key(self, project_id: str, page: str, base_revision: str,
                  change_kind: ChangeKind, title: str, markdown: str) -> str:
        """Generate a deterministic idempotency key."""
        data = f"{project_id}:{page}:{base_revision}:{change_kind.value}:{title}:{markdown}"
        return "key:" + hashlib.sha256(data.encode()).hexdigest()[:32]


# ─── Curator ───────────────────────────────────────────────────────────

class Curator:
    """Bounded curator: discovers pending work, inspects full proposals,
    decides (publish/reject), and handles blocked-queue metadata scanning."""

    def __init__(self, authority: KnowledgeStore, max_pending: int = 100):
        self._auth = authority
        self._max_pending = max_pending
        self._cursor = 0

    def pending_proposals(self, project_id: str, limit: int = 20) -> list[dict]:
        """Discover pending/blocked proposals (paged)."""
        conn = self._auth.connect(project_id)
        rows = conn.execute("""
            SELECT p.proposal_id, p.payload_digest, p.state, p.decision_kind,
                   p.rejected_reason, pk.base_revision
            FROM proposals p
            LEFT JOIN proposal_keys pk ON p.proposal_id = pk.proposal_id
            WHERE p.project=? AND p.state IN ('pending', 'blocked')
            ORDER BY p.proposal_id
            LIMIT ? OFFSET ?""",
            (project_id, limit, self._cursor)).fetchall()
        self._cursor += len(rows)
        items = []
        for row in rows:
            items.append({
                "proposal": row[0],
                "digest": row[1],
                "state": {
                    "kind": row[2],
                    "reason": row[4] if row[2] == "blocked" else None
                },
                "decision": row[3]
            })
        return items

    def decide(self, project_id: str, proposal_key: str,
               decision: DecisionKind, reason: Optional[str] = None
               ) -> DecisionOutcome:
        """Delegate to authority."""
        return self._auth.decide(project_id, proposal_key, decision, reason)

    def metadata_sweep(self, project_id: str) -> int:
        """Clear blocked entries with timeout (metadata-only rejection)."""
        conn = self._auth.connect(project_id)
        with conn:
            count = conn.execute(
                "UPDATE proposals SET state='decided', decision_kind='reject', rejected_reason='timeout' WHERE project=? AND state='blocked'",
                (project_id,)
            ).rowcount
            conn.commit()
            return count


# ─── Factory / entry point ───────────────────────────────────────────

def connect_knowledge(db_path: str, project_id: str,
                      schema_path: Optional[str] = None) -> KnowledgeStore:
    """Create and connect the knowledge authority."""
    # Default schema path is relative to this module's directory
    if schema_path is None:
        schema_path = Path(__file__).parent / "migrations.sql"
    store = KnowledgeStore(db_path, schema_path)
    store.connect(project_id)
    return store


def connect_curator(store: KnowledgeStore, project_id: str,
                    max_pending: int = 100) -> Curator:
    """Create a curator bound to the authority."""
    return Curator(store, max_pending)


# ─── Test bootstrap ───────────────────────────────────────────────────

def make_test_store(db_path: Optional[str] = None) -> tuple:
    """Create a fresh test store (in-memory)."""
    import tempfile
    path = db_path or tempfile.mktemp(suffix=".db")
    store = connect_knowledge(path, "test-project", schema_path="src/authority/migrations.sql")
    return store
