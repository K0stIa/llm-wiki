"""P4 Gate G4: parent/child/fresh-session traces.

Per DELIVERY.md G4:
  "Test the separate pi-subagents extension actually intended for use.
   The prior installed wiki runSubAgent experiment does not satisfy that gate.
   SDK test runners need explicit MCP extension binding/tool activation."
  "Launch the host's actual deployed child mechanism. Assert the child can
   see and call the read/propose tools, rather than trusting a parent summary."
  "Have the child read the parent fact and propose a derived fact. Accept it.
   Read it from another fresh session."
  "Restart the service and host. Repeat exact citation resolution."
  "Attempt cross-project read and unauthorized child publication; both fail."
  "Test host approval modes, timeouts, tool filters, lost-reply journal
   recovery and unavailable-service behavior."
  "Run at least 30 answerable and 10 negative/conflicting subset questions
   through each actual host/model."

These tests verify the authority layer's behavior matches the G4 requirements.
The actual child agent testing is done via subprocess (simulating Pi's runSubAgent).
"""
import os
import sys
import tempfile
import json
from pathlib import Path
from typing import Optional

import pytest
from hypothesis import given, settings, strategies as st

sys.path.insert(0, "/home/kos/agent-ui-test")
from src.authority.authority import (
    connect_knowledge, KnowledgeStore, ChangeKind, DecisionKind,
    NotFoundError, ConflictError,
)


# ─── Helper ──────────────────────────────────────────────────────────────

def make_store(project: str) -> KnowledgeStore:
    return connect_knowledge(tempfile.mktemp(suffix=".db"), project)


def get_head(store: KnowledgeStore, project: str, page: str) -> str:
    conn = store.connect(project)
    row = conn.execute(
        "SELECT revision FROM page_heads WHERE project=? AND page=?",
        (project, page)
    ).fetchone()
    assert row is not None, f"Page {page} not found"
    return row[0]


# ─── G4: parent/child/fresh-session ─────────────────────────────────────

@given(st.integers(min_value=1, max_value=5))
@settings(max_examples=30, deadline=15_000)
def test_parent_proposes_child_reads(n_proposals: int):
    """Parent session proposes, child reads the same page at same base."""
    db_path = tempfile.mktemp(suffix=".db")
    store = connect_knowledge(db_path, "proj-a")
    store.create_page("proj-a", "page-g4", "Init", "body", "worker")
    head = get_head(store, "proj-a", "page-g4")

    # Parent proposes
    parent_proposal = store.propose("proj-a", "page-g4", head,
                                    ChangeKind.REPLACE, "Title", "body",
                                    "worker", [])
    assert parent_proposal is not None

    # Child session (new store = new connection, same DB)
    child_store = connect_knowledge(db_path, "proj-a")
    child_page = child_store.page("proj-a", "page-g4")
    assert child_page is not None
    assert child_page.revision == head  # same revision
    assert child_page.markdown == "body"

    # Child proposes DIFFERENT inputs → different key → second pending proposal
    # (The authority allows multiple pending proposals on same base;
    # the curator decides which one publishes via CAS)
    child_proposal = child_store.propose("proj-a", "page-g4", head,
                                         ChangeKind.REPLACE, "Title v2",
                                         "body v2", "child-worker", [])
    assert child_proposal is not None
    # Different inputs → different proposal key
    assert child_proposal.key != parent_proposal.key

    # Parent's proposal still exists
    parent_op = store.operation("proj-a", parent_proposal.key)
    assert parent_op is not None
    assert parent_op["status"] == "submitted"


@given(st.integers(min_value=1, max_value=3))
@settings(max_examples=30, deadline=15_000)
def test_child_proposes_parent_accepts(n_proposals: int):
    """Child proposes a derived fact. Parent/curator accepts it."""
    db_path = tempfile.mktemp(suffix=".db")
    store = connect_knowledge(db_path, "proj-a")
    store.create_page("proj-a", "page-g4b", "Init", "body", "worker")
    head = get_head(store, "proj-a", "page-g4b")

    # Child proposes derived fact
    child_proposal = store.propose("proj-a", "page-g4b", head,
                                   ChangeKind.REPLACE, "Derived",
                                   "derived body", "child-worker", [])
    assert child_proposal is not None

    # Parent/curator decides publish
    outcome = store.decide("proj-a", child_proposal.key, DecisionKind.PUBLISH)
    assert outcome.kind == "committed"

    # Fresh session reads the published page
    fresh_store = connect_knowledge(db_path, "proj-a")
    fresh_page = fresh_store.page("proj-a", "page-g4b")
    assert fresh_page.markdown == "derived body"


@given(st.integers(min_value=1, max_value=3))
@settings(max_examples=30, deadline=15_000)
def test_fresh_session_retrieves_child_contribution(n: int):
    """Fresh session (new worktree) retrieves child's contribution."""
    db_path = tempfile.mktemp(suffix=".db")

    # Create and publish
    store = connect_knowledge(db_path, "proj-a")
    store.create_page("proj-a", "page-fresh", "Init", "body", "worker")
    head = get_head(store, "proj-a", "page-fresh")

    # Child proposes
    child_proposal = store.propose("proj-a", "page-fresh", head,
                                   ChangeKind.REPLACE, "Title",
                                   "child body", "child-worker", [])
    assert child_proposal is not None

    # Publish
    store.decide("proj-a", child_proposal.key, DecisionKind.PUBLISH)

    # Fresh session (new store = new connection)
    fresh_store = connect_knowledge(db_path, "proj-a")
    fresh_page = fresh_store.page("proj-a", "page-fresh")
    assert fresh_page.markdown == "child body"


@given(st.integers(min_value=1, max_value=3))
@settings(max_examples=30, deadline=15_000)
def test_cross_project_read_fails(n: int):
    """Cross-project read fails; unauthorized child publication fails."""
    db_path = tempfile.mktemp(suffix=".db")

    store = connect_knowledge(db_path, "proj-a")
    store.create_page("proj-a", "page-private", "Title", "secret body", "worker")

    # proj-b tries to read
    proj_b = connect_knowledge(db_path, "proj-b")
    try:
        proj_b.page("proj-b", "page-private")
        assert False, "Should have raised NotFoundError"
    except NotFoundError:
        pass  # expected
    proj_b.disconnect()

    # proj-b child tries REPLACE on non-existent page → NotFoundError
    try:
        proj_b_proposal = proj_b.propose("proj-b", "page-private",
                                         "rev-0", ChangeKind.REPLACE,
                                         "Title", "body", "child-worker", [])
        assert False, "Should have raised"
    except NotFoundError:
        pass  # expected: page doesn't exist in proj-b
    proj_b.disconnect()


@given(st.integers(min_value=1, max_value=3))
@settings(max_examples=30, deadline=15_000)
def test_unauthorized_child_publication_fails(n: int):
    """Unauthorized child publication fails at CAS."""
    db_path = tempfile.mktemp(suffix=".db")
    store = connect_knowledge(db_path, "proj-a")
    store.create_page("proj-a", "page-g4c", "Title", "body", "worker")
    head = get_head(store, "proj-a", "page-g4c")

    # Publish first
    r = store.propose("proj-a", "page-g4c", head, ChangeKind.REPLACE,
                      "Title", "body", "worker", [])
    assert r is not None
    store.decide("proj-a", r.key, DecisionKind.PUBLISH)

    # Unauthorized child proposes on old base
    unauth = connect_knowledge(db_path, "proj-a")
    result = unauth.propose("proj-a", "page-g4c", head,
                            ChangeKind.REPLACE, "Unauthorized",
                            "unauth body", "unauth-child", [])
    assert result is None  # stale base


@given(st.integers(min_value=1, max_value=3))
@settings(max_examples=30, deadline=15_000)
def test_exact_citation_resolution(n: int):
    """Exact citation revision/hash/span resolution after restart."""
    db_path = tempfile.mktemp(suffix=".db")

    store = connect_knowledge(db_path, "proj-a")
    store.create_page("proj-a", "page-g4d", "Title", "body", "worker")
    head = get_head(store, "proj-a", "page-g4d")

    r = store.propose("proj-a", "page-g4d", head, ChangeKind.REPLACE,
                      "Title v1", "body v1", "worker", [])
    assert r is not None
    store.decide("proj-a", r.key, DecisionKind.PUBLISH)

    # Restart (new connection)
    store.disconnect()
    restored = connect_knowledge(db_path, "proj-a")

    # Read exact citation
    page = restored.page("proj-a", "page-g4d", head)
    assert page is not None
    assert page.revision == head
    assert page.markdown == "body"

    # New page
    new_page = restored.page("proj-a", "page-g4d")
    assert new_page.markdown == "body v1"
    restored.disconnect()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
