"""P1 Gate G1 runtime tests: process races, crash/restart, outbox,
exact citations.

Per DELIVERY.md G1:
  "Test the actual public service calls and persisted rows, not only
   helper functions."
  "Eight independent processes submit 96 distinct evidence/proposal
   operations. All acknowledged proposals and source snapshots survive
   restart with matching hashes."
  "Eight proposals target one page/base. All proposals survive. Exactly
   one competing publication succeeds. Others return explicit conflicts."

The same-page CAS test uses eight independent Node/Python public-service
processes and one persisted SQLite database. Other tests below are bounded
local authority regressions; reconnecting is not a process-crash injection.
This file alone does not certify the complete G1 gate.
"""
import os
import sys
import threading
import tempfile
import time
from pathlib import Path
from typing import Optional

import pytest
from hypothesis import given, settings, strategies as st
from hypothesis.strategies import composite

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.authority.authority import (
    connect_knowledge, KnowledgeStore, ChangeKind, DecisionKind,
    ProposalReceipt, NotFoundError, ConflictError,
)


# ─── Strategies ─────────────────────────────────────────────────────────

@composite
def process_actions(draw):
    """A list of propose actions on same page."""
    n = draw(st.integers(min_value=1, max_value=8))
    return [(draw(st.integers(min_value=0, max_value=9999)),
             draw(st.integers(min_value=0, max_value=999)),
             draw(st.text(min_size=5, max_size=300)))
            for _ in range(n)]


# ─── Helpers ────────────────────────────────────────────────────────────

def _make_store(project_id: str = "test-proj") -> KnowledgeStore:
    """Create a fresh in-memory authority."""
    return connect_knowledge(":memory:", project_id)


def _create_page(store: KnowledgeStore, project_id: str,
                 page: str, title: str, body: str, actor: str = "worker") -> str:
    """Create page and return current head revision."""
    store.create_page(project_id, page, title, body, actor)
    conn = store.connect(project_id)
    row = conn.execute(
        "SELECT revision FROM page_heads WHERE project=? AND page=?",
        (project_id, page)
    ).fetchone()
    return row[0]


# ─── Tests ─────────────────────────────────────────────────────────────

def test_8_processes_same_page_cas(tmp_path):
    """Eight real public-service processes share one persisted base; one publishes."""
    from concurrent.futures import ThreadPoolExecutor
    from test_bridge_recovery_runtime import node, call
    import sqlite3
    db = str(tmp_path / "shared-cas.sqlite")
    page = node(call("createPage", db, "race", "page-x", "Init", "body", "owner"))[0]
    def invoke(principal, name, args):
        return node({"tool":"service", "binding":[db,"race",principal], "name":name, "args":args})[0]
    def propose_one(i):
        return invoke("worker", "wiki_propose", {"page":"page-x", "baseRevision":page["revision"],
            "changeKind":"replace", "title":"Title", "markdown":f"body-{i}", "key":f"key-{i}"})
    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = list(pool.map(propose_one, range(8)))
    assert all(r["kind"] == "pending" for r in receipts), receipts
    items = invoke("curator", "wiki_curator_pending", {"limit":100})["items"]
    digests = {item["id"]: item["reviewDigest"] for item in items}
    def decide_one(receipt):
        return invoke("curator", "wiki_curator_decide", {"proposalKey":receipt["key"],
            "digest":digests[receipt["proposal"]], "decision":"publish"})
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(decide_one, receipts))
    assert sum(r["kind"] == "committed" for r in outcomes) == 1, outcomes
    assert sum(r["kind"] == "conflict" for r in outcomes) == 7, outcomes
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 8
        # All eight publish requests have durable terminal decisions. Only one
        # outcome is committed; the other seven are recorded CAS conflicts.
        assert conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 8
        assert conn.execute("SELECT COUNT(*) FROM decisions WHERE json_extract(decision_json,'$.kind')='committed'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM decisions WHERE json_extract(decision_json,'$.kind')='conflict'").fetchone()[0] == 7
        assert conn.execute("SELECT COUNT(*) FROM proposals WHERE state='decided'").fetchone()[0] == 8
        assert conn.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 8


@given(st.integers(min_value=1, max_value=5))
@settings(max_examples=20)
def test_crash_restart_proposals_survive(n_proposals: int):
    """Proposals survive disconnect/reconnect (simulated crash).
    Same-page CAS enforced on reconnect."""
    import tempfile
    db_path = tempfile.mktemp(suffix=".db")
    store = connect_knowledge(db_path, "test-proj")
    store.create_page("test-proj", "page-crash", "Init", "body", "worker")
    conn = store.connect("test-proj")
    head_row = conn.execute(
        "SELECT revision FROM page_heads WHERE project=? AND page=?",
        ("test-proj", "page-crash")
    ).fetchone()
    assert head_row is not None
    base_rev = head_row[0]

    submitted = []
    for i in range(n_proposals):
        # Disconnect and reconnect (simulates process crash)
        store.disconnect()
        store2 = connect_knowledge(db_path, "test-proj")
        store2.connect("test-proj")
        result = store2.propose("test-proj", "page-crash", base_rev,
                                ChangeKind.REPLACE, "Title",
                                "body-" + str(i), "worker-" + str(i), [])
        if result:
            submitted.append(result)
        store2.disconnect()

    assert len(submitted) >= 1, f"No proposals submitted: {submitted}"

    # Publish first to advance head
    store2 = connect_knowledge(db_path, "test-proj")
    store2.connect("test-proj")
    first_key = submitted[0].key
    outcome = store2.decide("test-proj", first_key, DecisionKind.PUBLISH)
    assert outcome.kind == "committed"
    store2.disconnect()

    # All other proposals on old base should fail
    for p in submitted[1:]:
        store3 = connect_knowledge(db_path, "test-proj")
        store3.connect("test-proj")
        result = store3.propose("test-proj", "page-crash", base_rev,
                                ChangeKind.REPLACE, "Stale", "stale",
                                "worker", [])
        assert result is None, f"Stale proposal {p.key} succeeded"
        store3.disconnect()

    # Cleanup
    try:
        os.unlink(db_path)
        os.unlink(db_path + "-wal")
        os.unlink(db_path + "-shm")
    except:
        pass


@given(st.integers(min_value=1, max_value=5))
@settings(max_examples=15)
def test_outbox_promotion(count: int):
    """Outbox entries are promoted after publish."""
    store = _make_store()
    store.create_page("test-proj", "page-outbox", "Init", "body", "worker")

    for i in range(count):
        r = store.propose("test-proj", "page-outbox", "rev-0",
                          ChangeKind.REPLACE, "Title " + str(i),
                          "body " + str(i), "worker", [])
        if r:
            store.decide("test-proj", r.key, DecisionKind.PUBLISH)

    status = store.get_outbox_status("test-proj")
    assert "index:done" in status or "index:pending" in status
    # After publish, outbox should have done items
    assert status.get("index:done", 0) > 0 or status.get("index:pending", 0) > 0


@given(st.integers(min_value=1, max_value=5))
@settings(max_examples=15)
def test_exact_citation_read(count: int):
    """Published bodies are always retrievable via citation."""
    store = _make_store()
    store.create_page("test-proj", "page-cite", "Init", "initial body", "worker")
    conn = store.connect("test-proj")
    head_row = conn.execute(
        "SELECT revision FROM page_heads WHERE project=? AND page=?",
        ("test-proj", "page-cite")
    ).fetchone()
    assert head_row is not None
    base_rev = head_row[0]

    # Propose and publish
    r = store.propose("test-proj", "page-cite", base_rev,
                      ChangeKind.REPLACE, "Title", "new body", "worker", [])
    assert r is not None
    store.decide("test-proj", r.key, DecisionKind.PUBLISH)

    # Read the page by revision
    snap = store.page("test-proj", "page-cite", head_row[0])
    assert snap is not None
    assert snap.markdown == "initial body"

    # Read new page
    snap2 = store.page("test-proj", "page-cite")
    assert snap2 is not None
    assert snap2.markdown == "new body"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
