"""Hypothesis tests for the KnowledgeStore authority layer.

Properties tested:
- CAS: only one publish succeeds per page base
- Idempotency: same key returns same proposal
- Stale rejection: post-publish proposals on old base fail
- Immutability: published bodies are never modified
- Retired page rejection: proposals on retired pages fail
"""
import sys
sys.path.insert(0, "/home/kos/agent-ui-test")
from typing import Optional

import pytest
from hypothesis import given, settings, strategies as st
from hypothesis.strategies import composite

from src.authority.authority import (
    KnowledgeStore, ProposalReceipt, DecisionOutcome,
    DecisionKind, ChangeKind,
    connect_knowledge,
)


# ─── Strategies ─────────────────────────────────────────────────────────

@composite
def change_action(draw):
    n = draw(st.integers(min_value=0, max_value=9999))
    kind = draw(st.sampled_from([ChangeKind.REPLACE, ChangeKind.RETIRE]))
    body = draw(st.text(min_size=5, max_size=300))
    return (f"k-{n}", kind, body)


@composite
def valid_create_action(draw):
    n = draw(st.integers(min_value=0, max_value=999))
    body = draw(st.text(min_size=5, max_size=200))
    return (f"c-{n}", body)


def _get_head(store: KnowledgeStore, project_id: str, page: str) -> Optional[str]:
    conn = store.connect(project_id)
    row = conn.execute(
        "SELECT revision FROM page_heads WHERE project=? AND page=?",
        (project_id, page)
    ).fetchone()
    return row[0] if row else None


# ─── Tests ─────────────────────────────────────────────────────────────

@given(st.lists(change_action(), min_size=1, max_size=30))
@settings(max_examples=300, deadline=10_000)
def test_cas_exactly_one_wins(actions: list):
    """Only one publish succeeds per page base (CAS invariant)."""
    store = connect_knowledge(":memory:", "test-proj")
    store.create_page("test-proj", "page-a", "Initial", "initial body", "worker")
    head = _get_head(store, "test-proj", "page-a")
    assert head is not None

    proposals: list[ProposalReceipt] = []
    for key, kind, body in actions:
        result = store.propose("test-proj", "page-a", head, kind,
                               f"Title {kind.value}", body, "worker", [])
        if result:
            proposals.append(result)

    published = []
    for p in proposals:
        outcome = store.decide("test-proj", p.key, DecisionKind.PUBLISH)
        if outcome.kind == "committed":
            published.append(outcome)

    assert len(published) <= 1, f"Multiple published: {len(published)}"
    store.disconnect()


@given(st.lists(change_action(), min_size=1, max_size=30))
@settings(max_examples=300, deadline=10_000)
def test_idempotency_same_key(actions: list):
    """Calling propose with the same key twice yields the same result."""
    store = connect_knowledge(":memory:", "test-proj")
    store.create_page("test-proj", "page-a", "Initial", "initial body", "worker")
    head = _get_head(store, "test-proj", "page-a")

    for key, kind, body in actions:
        result1 = store.propose("test-proj", "page-a", head, kind,
                                "Title", body, "worker", [])
        assert result1 is not None
        result2 = store.propose("test-proj", "page-a", head, kind,
                                "Title", body, "worker", [])
        assert result2.proposal == result1.proposal
        assert result2.key == result1.key
    store.disconnect()


@given(st.lists(change_action(), min_size=1, max_size=15))
@settings(max_examples=200, deadline=10_000)
def test_stale_base_after_publish(actions: list):
    """After publish, stale-base proposals fail."""
    store = connect_knowledge(":memory:", "test-proj")
    store.create_page("test-proj", "page-a", "Initial", "initial body", "worker")
    head = _get_head(store, "test-proj", "page-a")

    proposals = []
    for key, kind, body in actions:
        result = store.propose("test-proj", "page-a", head, kind,
                               "Title", body, "worker", [])
        if result:
            proposals.append(result)

    if proposals:
        store.decide("test-proj", proposals[0].key, DecisionKind.PUBLISH)

    for p in proposals:
        result = store.propose("test-proj", "page-a", head, ChangeKind.REPLACE,
                               "Stale Title", "stale body", "worker", [])
        assert result is None, f"Stale proposal succeeded"

    store.disconnect()


@given(st.lists(valid_create_action(), min_size=1, max_size=20))
@settings(max_examples=200, deadline=10_000)
def test_body_recoverable_after_publish(actions: list):
    """Published bodies are always retrievable."""
    store = connect_knowledge(":memory:", "test-proj")
    proposed: dict[str, ProposalReceipt] = {}
    for key, body in actions:
        page_name = f"page-{key[2:]}"
        store.create_page("test-proj", page_name, f"Title {key}", body, "worker")
        head = _get_head(store, "test-proj", page_name)
        result = store.propose("test-proj", page_name, head, ChangeKind.REPLACE,
                               f"Title {key}", body, "worker", [])
        if result:
            proposed[page_name] = (result, body)

    if not proposed:
        store.disconnect()
        return

    first_page = list(proposed.keys())[0]
    store.decide("test-proj", proposed[first_page][0].key, DecisionKind.PUBLISH)

    snap = store.page("test-proj", first_page)
    assert snap is not None
    assert snap.markdown == proposed[first_page][1]
    store.disconnect()


@given(st.lists(change_action(), min_size=2, max_size=20))
@settings(max_examples=150, deadline=10_000)
def test_retired_page_rejects_proposals(actions: list):
    """Proposing on a retired page returns conflict."""
    store = connect_knowledge(":memory:", "test-proj")
    store.create_page("test-proj", "page-a", "Initial", "initial body", "worker")
    head_a = _get_head(store, "test-proj", "page-a")

    result1 = store.propose("test-proj", "page-a", head_a, ChangeKind.REPLACE,
                            "Title", "new body", "worker", [])
    assert result1 is not None
    store.decide("test-proj", result1.key, DecisionKind.PUBLISH)

    store.create_page("test-proj", "page-b", "Other", "other body", "worker")
    head_b = _get_head(store, "test-proj", "page-b")
    result2 = store.propose("test-proj", "page-b", head_b, ChangeKind.RETIRE,
                            "Title", "", "worker", [])
    if result2:
        store.decide("test-proj", result2.key, DecisionKind.PUBLISH)

    for key, kind, body in actions:
        result = store.propose("test-proj", "page-b", head_b, kind,
                               "Title", body, "worker", [])
        assert result is None, f"Proposal on retired page succeeded"

    store.disconnect()
