"""G1: every row of the proposal state table (ARCHITECTURE.md), one named test each.

| Current state     | Request/event                                    | Result                                   |
|-------------------|--------------------------------------------------|------------------------------------------|
| pending           | publish, current review, head CAS succeeds       | decided/committed                        |
| pending           | same publish, head CAS loses                     | decided/conflict                         |
| pending           | supervisor records failure                       | blocked with reason                      |
| pending or blocked| metadata-only reject                             | decided/rejected, unresolved slot freed  |
| blocked           | publish                                          | invalid-state, no publication            |
| decided           | identical decision replay                        | original durable result                  |
| decided           | contradictory decision or later blocked event    | terminal error / no-op, never mutation   |

Plus: stale review digests, and publish-vs-block / publish-vs-reject orderings,
both forced (deterministic) and raced across processes (stress).

Oversize review-bundle admission is NOT here: it needs the frozen G0 curator
profile and token-count bound, which do not exist yet (gates.json: g1.oversize-admission).
"""
import json
import multiprocessing
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "authority"))
sys.path.insert(0, str(ROOT / "src" / "mcp"))
from authority import (ChangeKind, DecisionKind, InvalidInputError,  # noqa: E402
                       connect_knowledge)
import authority_rpc  # noqa: E402

P = "alpha"


def snapshot(db):
    with sqlite3.connect(db) as c:
        return {
            "proposals": c.execute("SELECT proposal_id,state,decision_kind,decision_json,rejected_reason FROM proposals ORDER BY proposal_id").fetchall(),
            "decisions": c.execute("SELECT * FROM decisions ORDER BY proposal_id").fetchall(),
            "heads": c.execute("SELECT page,revision,state FROM page_heads ORDER BY page").fetchall(),
            "sequence": c.execute("SELECT sequence FROM projects").fetchone()[0],
            "outbox": c.execute("SELECT COUNT(*) FROM outbox").fetchone()[0],
            "fts": c.execute("SELECT revision FROM retrieval_chunks WHERE kind='page' ORDER BY revision").fetchall(),
        }


def unresolved(db):
    with sqlite3.connect(db) as c:
        return c.execute("SELECT COUNT(*) FROM proposals WHERE state IN ('pending','blocked')").fetchone()[0]


def state_of(db, key):
    with sqlite3.connect(db) as c:
        return c.execute("SELECT p.state,p.decision_kind,p.rejected_reason FROM proposals p JOIN proposal_keys k "
                         "ON k.proposal_id=p.proposal_id WHERE k.key=?", (key,)).fetchone()


@pytest.fixture()
def world(tmp_path):
    db = tmp_path / "authority.sqlite"
    store = connect_knowledge(str(db), P)
    base = store.create_page(P, "page", "Title", "Original", "owner").revision

    def propose(key, body="Changed"):
        receipt = store.propose(P, "page", base, ChangeKind.REPLACE, "Title", body, "worker", [], key=key)
        assert receipt and receipt.kind == "pending"
        return key

    yield db, store, base, propose
    store.disconnect()


# ─── pending ──────────────────────────────────────────────────────────

def test_pending_publish_with_winning_cas_commits(world):
    db, store, base, propose = world
    key = propose("k1")
    outcome = store.decide(P, key, DecisionKind.PUBLISH)
    assert outcome.kind == "committed"
    assert state_of(db, key)[:2] == ("decided", "publish")
    assert snapshot(db)["heads"] == [("page", outcome.page_revision, "active")]


def test_pending_publish_with_losing_cas_is_terminal_conflict(world):
    db, store, base, propose = world
    winner, loser = propose("win", "A"), propose("lose", "B")
    committed = store.decide(P, winner, DecisionKind.PUBLISH)
    outcome = store.decide(P, loser, DecisionKind.PUBLISH)
    assert outcome.kind == "conflict" and outcome.current == committed.page_revision
    assert state_of(db, loser)[:2] == ("decided", "publish")
    assert snapshot(db)["heads"] == [("page", committed.page_revision, "active")]
    # Conflict is terminal: the losing proposal is kept, and replay returns the same conflict.
    assert store.decide(P, loser, DecisionKind.PUBLISH) == outcome


def test_pending_supervisor_failure_blocks_with_reason(world):
    db, store, base, propose = world
    key = propose("k1")
    before = snapshot(db)
    assert store.block(P, key, "review deadline exceeded") == "blocked"
    assert state_of(db, key) == ("blocked", None, "review deadline exceeded")
    after = snapshot(db)
    assert (after["heads"], after["sequence"], after["outbox"], after["fts"]) == \
           (before["heads"], before["sequence"], before["outbox"], before["fts"])


@pytest.mark.parametrize("start", ["pending", "blocked"])
def test_metadata_reject_from_pending_or_blocked_frees_slot(world, start):
    db, store, base, propose = world
    key = propose("k1")
    if start == "blocked":
        store.block(P, key, "context too large for reviewer")
    before = snapshot(db)
    assert unresolved(db) == 1
    outcome = store.reject_metadata(P, key, "not reviewable")
    assert outcome.kind == "rejected" and outcome.reason == "not reviewable"
    assert unresolved(db) == 0
    after = snapshot(db)
    assert (after["heads"], after["sequence"], after["outbox"], after["fts"]) == \
           (before["heads"], before["sequence"], before["outbox"], before["fts"])


# ─── blocked ──────────────────────────────────────────────────────────

def test_blocked_publish_is_invalid_state_without_publication(world):
    db, store, base, propose = world
    key = propose("k1")
    store.block(P, key, "policy failure")
    before = snapshot(db)
    with pytest.raises(InvalidInputError, match="blocked"):
        store.decide(P, key, DecisionKind.PUBLISH)
    assert snapshot(db) == before


def test_blocked_repeated_supervisor_event_is_noop(world):
    db, store, base, propose = world
    key = propose("k1")
    store.block(P, key, "first reason")
    before = snapshot(db)
    assert store.block(P, key, "second reason") == "blocked"
    assert snapshot(db) == before and state_of(db, key)[2] == "first reason"


# ─── decided ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("terminal", ["committed", "conflict", "rejected"])
def test_decided_identical_replay_returns_original_result(world, terminal):
    db, store, base, propose = world
    key = propose("k1")
    if terminal == "conflict":
        store.decide(P, propose("other", "X"), DecisionKind.PUBLISH)
    if terminal == "rejected":
        first = store.reject_metadata(P, key, "dup")
        replay = lambda: store.reject_metadata(P, key, "dup")  # noqa: E731
    else:
        first = store.decide(P, key, DecisionKind.PUBLISH)
        replay = lambda: store.decide(P, key, DecisionKind.PUBLISH)  # noqa: E731
    assert first.kind == terminal
    before = snapshot(db)
    assert replay() == first
    assert snapshot(db) == before


@pytest.mark.parametrize("first,second", [("publish", "reject"), ("reject", "publish"), ("reject", "reject-other-reason")])
def test_decided_contradictory_decision_fails_without_mutation(world, first, second):
    db, store, base, propose = world
    key = propose("k1")
    if first == "publish":
        store.decide(P, key, DecisionKind.PUBLISH)
    else:
        store.reject_metadata(P, key, "reason")
    before = snapshot(db)
    with pytest.raises(InvalidInputError):
        if second == "publish":
            store.decide(P, key, DecisionKind.PUBLISH)
        elif second == "reject":
            store.reject_metadata(P, key, "reason")
        else:
            store.reject_metadata(P, key, "a different reason")
    assert snapshot(db) == before


@pytest.mark.parametrize("terminal", ["committed", "rejected"])
def test_decided_later_blocked_event_is_noop(world, terminal):
    db, store, base, propose = world
    key = propose("k1")
    if terminal == "committed":
        store.decide(P, key, DecisionKind.PUBLISH)
    else:
        store.reject_metadata(P, key, "reason")
    before = snapshot(db)
    assert store.block(P, key, "late review timeout") == "decided"
    assert snapshot(db) == before


def test_block_and_reject_unknown_or_foreign_proposal_fail(world):
    db, store, base, propose = world
    from authority import NotFoundError
    with pytest.raises(NotFoundError):
        store.block(P, "missing", "x")
    with pytest.raises(NotFoundError):
        store.reject_metadata(P, "missing", "x")
    with pytest.raises(InvalidInputError):
        store.block(P, propose("k1"), "")


# ─── review digest binding ────────────────────────────────────────────

def test_publish_with_stale_or_payload_digest_is_refused(world):
    db, store, base, propose = world
    key = propose("k1")
    with sqlite3.connect(db) as c:
        proposal, payload = c.execute("SELECT proposal_id,payload_digest FROM proposals").fetchone()
    current = authority_rpc.review_digest(store, P, proposal, payload)
    before = snapshot(db)
    for digest in (payload, "review:" + "0" * 64, None):
        with pytest.raises(PermissionError):
            authority_rpc.dispatch(str(db), P, "curator", "wiki_curator_decide",
                                   {"proposalKey": key, "digest": digest, "decision": "publish"})
    assert snapshot(db) == before
    # A restore changes the epoch, so a review done before it no longer attests.
    with sqlite3.connect(db) as c:
        c.execute("UPDATE projects SET epoch='restored'")
    with pytest.raises(PermissionError):
        authority_rpc.dispatch(str(db), P, "curator", "wiki_curator_decide",
                               {"proposalKey": key, "digest": current, "decision": "publish"})
    assert state_of(db, key)[0] == "pending"


# ─── races: forced orderings (deterministic) ──────────────────────────

@pytest.mark.parametrize("order", ["publish-then-block", "block-then-publish",
                                   "publish-then-reject", "reject-then-publish"])
def test_forced_orderings_have_exactly_one_terminal_outcome(world, order):
    db, store, base, propose = world
    key = propose("k1")
    start_sequence = snapshot(db)["sequence"]
    first, _, second = order.partition("-then-")
    results = {}
    for step in (first, second):
        try:
            if step == "publish":
                results[step] = store.decide(P, key, DecisionKind.PUBLISH).kind
            elif step == "block":
                results[step] = store.block(P, key, "deadline")
            else:
                results[step] = store.reject_metadata(P, key, "metadata").kind
        except InvalidInputError:
            results[step] = "refused"
    expected = {
        "publish-then-block": {"publish": "committed", "block": "decided"},
        "block-then-publish": {"block": "blocked", "publish": "refused"},
        "publish-then-reject": {"publish": "committed", "reject": "refused"},
        "reject-then-publish": {"reject": "rejected", "publish": "refused"},
    }[order]
    assert results == expected
    s = snapshot(db)
    published = s["sequence"] == start_sequence + 1
    assert published == (order.startswith("publish"))
    assert len(s["decisions"]) == (0 if order == "block-then-publish" else 1)


# ─── races: real processes (stress, not proof of every interleaving) ──

def _actor(db, key, action, barrier, out):
    sys.path.insert(0, str(ROOT / "src" / "authority"))
    from authority import connect_knowledge as connect, DecisionKind as D, InvalidInputError as Invalid
    store = connect(str(db), P)
    barrier.wait()
    try:
        if action == "publish":
            out.put((action, store.decide(P, key, D.PUBLISH).kind))
        elif action == "block":
            out.put((action, store.block(P, key, "deadline")))
        else:
            out.put((action, store.reject_metadata(P, key, "metadata").kind))
    except Invalid:
        out.put((action, "refused"))
    finally:
        store.disconnect()


@pytest.mark.parametrize("other", ["block", "reject"])
def test_raced_publish_against_block_or_reject_never_double_terminates(world, other):
    db, store, base, propose = world
    ctx = multiprocessing.get_context("spawn")
    for round_ in range(5):
        page = f"race-{other}-{round_}"
        head = store.create_page(P, page, "Title", "Original", "owner").revision
        key = f"key-{page}"
        assert store.propose(P, page, head, ChangeKind.REPLACE, "Title", "Changed", "worker", [], key=key)
        start_sequence = snapshot(db)["sequence"]
        barrier, out = ctx.Barrier(2), ctx.Queue()
        procs = [ctx.Process(target=_actor, args=(db, key, action, barrier, out)) for action in ("publish", other)]
        for proc in procs:
            proc.start()
        for proc in procs:
            proc.join(60)
            assert proc.exitcode == 0
        results = dict(out.get(timeout=5) for _ in procs)
        state, kind, _ = state_of(db, key)
        if results["publish"] == "committed":
            assert kind == "publish" and results[other] in ("decided", "refused")
            assert snapshot(db)["sequence"] == start_sequence + 1
        else:
            assert results["publish"] == "refused"
            assert (state, kind) == (("blocked", None) if other == "block" else ("decided", "reject"))
            assert snapshot(db)["sequence"] == start_sequence
        with sqlite3.connect(db) as c:
            decisions = c.execute("SELECT COUNT(*) FROM decisions d JOIN proposal_keys k ON k.proposal_id=d.proposal_id "
                                  "WHERE k.key=?", (key,)).fetchone()[0]
        assert decisions == (0 if state == "blocked" else 1)
