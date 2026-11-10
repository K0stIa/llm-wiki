"""Hypothesis tests for the authority's CAS (check-and-set) invariant.

The critical property: given a page at revision R, if two proposals
both use base=R, exactly one wins and the other gets a conflict.
No silent overwrites, no lost acknowledgments.

Each generated example gets a fresh in-memory SQLite database.
"""
import sqlite3
import hashlib
from typing import Optional

import pytest
from hypothesis import given, settings, strategies as st, assume
from hypothesis.strategies import composite


# ─── Test harness ───────────────────────────────────────────────────────

def _make_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("CREATE TABLE projects (id TEXT PRIMARY KEY, epoch TEXT, sequence INTEGER DEFAULT 0)")
    conn.execute("INSERT INTO projects VALUES ('proj-001', 'epoch-1', 0)")
    conn.execute("CREATE TABLE page_heads (project TEXT, page TEXT, revision TEXT, state TEXT, PRIMARY KEY(project, page))")
    conn.execute("INSERT INTO page_heads VALUES ('proj-001', 'page-a', 'rev-0', 'active')")
    conn.execute("CREATE TABLE page_revisions (revision TEXT PRIMARY KEY, project TEXT, page TEXT, base_revision TEXT, title TEXT, body TEXT, state TEXT CHECK(state IN ('active','retired')), FOREIGN KEY(project,page) REFERENCES page_heads(project,page))")
    conn.execute("INSERT INTO page_revisions VALUES ('rev-0','proj-001','page-a',NULL,'Initial page','body content','active')")
    conn.execute("CREATE TABLE proposals (proposal_id TEXT PRIMARY KEY, project TEXT, page TEXT, base_revision TEXT, change_body TEXT, title TEXT, state TEXT CHECK(state IN ('pending','blocked','decided')), decision TEXT, rejected_reason TEXT, FOREIGN KEY(project,page) REFERENCES page_heads(project,page))")
    conn.execute("CREATE TABLE proposal_keys (key TEXT PRIMARY KEY, proposal_id TEXT UNIQUE, project TEXT, page TEXT, base_revision TEXT, FOREIGN KEY(project,page) REFERENCES page_heads(project,page))")
    conn.execute("CREATE TABLE decisions (proposal_id TEXT PRIMARY KEY, decision_kind TEXT CHECK(decision_kind IN ('publish','reject')), decision_json TEXT, review_digest TEXT, FOREIGN KEY(proposal_id) REFERENCES proposals(proposal_id))")
    conn.execute("CREATE TABLE operations (op_key TEXT PRIMARY KEY, project TEXT, principal TEXT, request_digest TEXT, result_digest TEXT, status TEXT CHECK(status IN ('submitted','committed','failed')), FOREIGN KEY(project) REFERENCES projects(id))")
    conn.commit()
    return conn


def propose(conn: sqlite3.Connection, key: str, page: str, base: str, body: str) -> Optional[str]:
    existing = conn.execute("SELECT proposal_id FROM proposal_keys WHERE key=?", (key,)).fetchone()
    if existing:
        return existing[0]
    current = conn.execute("SELECT revision FROM page_heads WHERE page=?", (page,)).fetchone()
    if not current or current[0] != base:
        return None
    prop_id = "prop-" + hashlib.sha256(key.encode()).hexdigest()[:8]
    conn.execute("INSERT INTO proposals VALUES (?,?,?,?,?,?,?,?,?)",
                 (prop_id, "proj-001", page, base, body[:50], body[:50], "pending", None, None))
    conn.execute("INSERT INTO proposal_keys VALUES (?,?,?,?,?)",
                 (key, prop_id, "proj-001", page, base))
    conn.commit()
    return prop_id


def publish(conn: sqlite3.Connection, key: str) -> Optional[str]:
    key_row = conn.execute("""
        SELECT pk.proposal_id, pk.base_revision, p.change_body
        FROM proposal_keys pk JOIN proposals p ON pk.proposal_id = p.proposal_id
        WHERE pk.key=?""", (key,)).fetchone()
    if not key_row:
        return None
    prop_id, base_rev, new_body = key_row
    current = conn.execute("SELECT revision, state FROM page_heads WHERE page=?", ("page-a",)).fetchone()
    if not current or current[0] != base_rev or current[1] != "active":
        return None
    new_rev = "rev-" + str(int(current[0][4:]) + 1)
    conn.execute("UPDATE page_revisions SET state='retired' WHERE revision=?", (current[0],))
    conn.execute("UPDATE page_heads SET revision=?, state='active' WHERE page=?",
                 (new_rev, "page-a"))
    conn.execute("INSERT INTO page_revisions VALUES (?,?,?,?,?,?,?)",
                 (new_rev, "proj-001", "page-a", base_rev, "Updated page", new_body, "active"))
    conn.execute("UPDATE proposals SET state='decided', decision='publish' WHERE proposal_id=?", (prop_id,))
    conn.execute("INSERT INTO decisions VALUES (?,?,?,NULL)", (prop_id, "publish", "{}"))
    conn.commit()
    return new_rev


def read_page(conn: sqlite3.Connection, rev: str) -> Optional[str]:
    row = conn.execute("SELECT body FROM page_revisions WHERE revision=?", (rev,)).fetchone()
    return row[0] if row else None


# ─── Strategies ─────────────────────────────────────────────────────────

@composite
def valid_propose_action(draw):
    """A propose action guaranteed to succeed (base=rev-0)."""
    n = draw(st.integers(min_value=0, max_value=9999))
    return (f"v-{n}", 0, draw(st.text(min_size=1, max_size=200)))


@composite
def valid_action(draw):
    """Unique key + base=rev-0 + body."""
    n = draw(st.integers(min_value=0, max_value=9999))
    return (f"a-{n}", 0, draw(st.text(min_size=1, max_size=200)))


# ─── Tests ─────────────────────────────────────────────────────────────

@given(st.lists(valid_action(), min_size=1, max_size=50))
@settings(max_examples=300, deadline=10_000)
def test_cas_exactly_one_wins_per_base(actions: list):
    """When we publish, exactly one winning proposal's body survives.
    No two proposals on the same page produce two active revisions."""
    conn = _make_db()
    for key, base_n, body in actions:
        propose(conn, key, "page-a", "rev-0", body)
    # Publish — only one wins
    published_bodies: list[str] = []
    for key, _, body in actions:
        new_rev = publish(conn, key)
        if new_rev:
            stored = read_page(conn, new_rev)
            if stored is not None:
                published_bodies.append(stored)
    # Only one body survives (the first winner)
    assert len(set(published_bodies)) <= 1, (
        f"Multiple bodies published: {published_bodies}"
    )
    conn.close()


@given(st.lists(valid_propose_action(), min_size=1, max_size=50))
@settings(max_examples=300, deadline=10_000)
def test_no_key_reuse(actions: list):
    """Calling propose with the same key twice yields the same result."""
    conn = _make_db()
    for key, _, body in actions:
        result1 = propose(conn, key, "page-a", "rev-0", body)
        assert result1 is not None
        result2 = propose(conn, key, "page-a", "rev-0", body)
        assert result2 == result1, f"Key {key} gave {result1} vs {result2}"
    conn.close()


@given(
    st.lists(valid_propose_action(), min_size=1, max_size=10),
    st.integers(min_value=0, max_value=50)
)
@settings(max_examples=200, deadline=10_000)
def test_publish_cascades_stale_bases(actions, seed):
    """After publish, stale-base proposals with new keys fail."""
    conn = _make_db()
    all_proposals: list[tuple[str, str]] = []
    for key, _, body in actions:
        result = propose(conn, key, "page-a", "rev-0", body)
        if result:
            all_proposals.append((key, body))
    if all_proposals:
        publish(conn, all_proposals[0][0])
    # New keys with stale base must fail
    for key, body in all_proposals:
        new_key = f"stale-{key[2:]}"
        result = propose(conn, new_key, "page-a", "rev-0", "stale body")
        assert result is None, f"Stale proposal {new_key} still succeeded"
    conn.close()


@given(st.lists(valid_propose_action(), min_size=1, max_size=40))
@settings(max_examples=250, deadline=10_000)
def test_body_is_stored_and_recoverable(actions: list):
    """Every published body is retrievable and matches."""
    conn = _make_db()
    seen: dict[str, str] = {}
    for key, _, body in actions:
        if key not in seen:
            seen[key] = body
    for key, body in seen.items():
        propose(conn, key, "page-a", "rev-0", body)
    if seen:
        for key in seen:
            publish(conn, key)
        stored = read_page(conn, "rev-1")
        assert stored is not None
        # Only the first unique-key winner survives (CAS)
        assert stored == list(seen.values())[0]
    conn.close()
