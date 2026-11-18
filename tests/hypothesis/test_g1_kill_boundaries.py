"""G1: kill the authority process at named boundaries, restart, retry.

DELIVERY G1: "Kill the service at named boundaries before commit, after commit
before reply, and before/after index promotion. Restart and retry. Verify
receipts, heads, FTS and outbox from durable state."

Each call is the real one-shot RPC process (src/mcp/authority_rpc.py) that the
MCP stdio server and worker service launch. WIKI_TEST_FAULT_POINT makes it
os._exit(97) at exactly one named point: no commit, no rollback, no reply. Exit
97 proves the point was reached; the next process is the restart. Assertions
read the SQLite file directly, never the crashed process's output.

The derived-index generation swap (src/retrieval/qmd-integration.ts) needs the
embedding model and is not covered here; this file covers the authority side
of promotion (the outbox acknowledgement transaction).
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "authority"))
from authority import connect_knowledge  # noqa: E402
import faults  # noqa: E402

RPC = ROOT / "src" / "mcp" / "authority_rpc.py"
PROJECT = "alpha"
BODY = "Original body\nline two"
NEW_BODY = "Corrected body\nline two\nline three"


def rpc(db, principal, tool, args, fault=None):
    env = {k: v for k, v in os.environ.items() if k != faults.ENV}
    if fault:
        env[faults.ENV] = fault
    proc = subprocess.run([sys.executable, str(RPC), str(db), PROJECT, principal, tool],
                          input=json.dumps(args), capture_output=True, text=True, env=env, timeout=60)
    reply = json.loads(proc.stdout) if proc.stdout.strip() else None
    return proc.returncode, reply


def crash(db, principal, tool, args, point):
    code, reply = rpc(db, principal, tool, args, fault=point)
    assert code == faults.FAULT_EXIT, f"fault point {point} was not reached (exit {code}, reply {reply})"
    assert reply is None, "a crashed process must not have replied"


def ok(db, principal, tool, args):
    code, reply = rpc(db, principal, tool, args)
    assert code == 0, reply
    return reply


def added(before, after, table):
    return [row for row in after[table] if row not in before[table]]


def durable(db):
    """Everything G1 asks to verify, read straight from the file."""
    with sqlite3.connect(db) as c:
        assert c.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        return {
            "proposals": c.execute("SELECT proposal_id,state,decision_kind,decision_json FROM proposals ORDER BY proposal_id").fetchall(),
            "keys": c.execute("SELECT key,proposal_id FROM proposal_keys ORDER BY key").fetchall(),
            "operations": c.execute("SELECT op_key,principal,status FROM operations ORDER BY op_key").fetchall(),
            "decisions": c.execute("SELECT proposal_id,decision_kind,decision_json FROM decisions ORDER BY proposal_id").fetchall(),
            "heads": c.execute("SELECT page,revision,state FROM page_heads ORDER BY page").fetchall(),
            "revisions": c.execute("SELECT COUNT(*) FROM page_revisions").fetchone()[0],
            "sequence": c.execute("SELECT epoch,sequence FROM projects WHERE id=?", (PROJECT,)).fetchone(),
            "outbox": c.execute("SELECT id,revision,kind,status FROM outbox ORDER BY id").fetchall(),
            "fts": c.execute("SELECT object,revision FROM retrieval_chunks WHERE project=? AND kind='page' ORDER BY object,revision", (PROJECT,)).fetchall(),
            "generations": c.execute("SELECT project,generation,epoch,sequence,model_digest FROM retrieval_generations").fetchall(),
        }


@pytest.fixture()
def seeded(tmp_path):
    db = tmp_path / "authority.sqlite"
    store = connect_knowledge(str(db), PROJECT)
    page = store.create_page(PROJECT, "page", "Title", BODY, "owner")
    store.disconnect()
    return db, page.revision


def propose_args(base, key="worker-call-1"):
    return {"page": "page", "baseRevision": base, "changeKind": "replace", "title": "Title",
            "markdown": NEW_BODY, "sources": [], "key": key}


def pending_digest(db, key):
    items = ok(db, "curator", "wiki_curator_pending", {"limit": 100})["items"]
    with sqlite3.connect(db) as c:
        proposal = c.execute("SELECT proposal_id FROM proposal_keys WHERE key=?", (key,)).fetchone()[0]
    return next(i["reviewDigest"] for i in items if i["id"] == proposal)


def published(db, base):
    ok(db, "worker", "wiki_propose", propose_args(base))
    decide = {"proposalKey": "worker-call-1", "digest": pending_digest(db, "worker-call-1"), "decision": "publish"}
    return ok(db, "curator", "wiki_curator_decide", decide)


# ─── Proposal admission ───────────────────────────────────────────────

def test_kill_before_proposal_commit_leaves_nothing_and_retry_admits_once(seeded):
    db, base = seeded
    before = durable(db)
    crash(db, "worker", "wiki_propose", propose_args(base), "propose.before-commit")
    assert durable(db) == before, "an uncommitted proposal left durable rows"

    receipt = ok(db, "worker", "wiki_propose", propose_args(base))
    assert receipt["kind"] == "pending" and receipt["key"] == "worker-call-1"
    again = ok(db, "worker", "wiki_propose", propose_args(base))
    assert again == receipt
    state = durable(db)
    assert len(state["proposals"]) == 1 and state["proposals"][0][1] == "pending"
    assert state["operations"] == [("worker-call-1", "worker", "submitted")]
    assert state["heads"] == before["heads"] and state["sequence"] == before["sequence"]


def test_kill_after_proposal_commit_before_reply_retry_returns_original_receipt(seeded):
    db, base = seeded
    before = durable(db)
    crash(db, "worker", "wiki_propose", propose_args(base), "rpc.after-commit-before-reply")
    committed = durable(db)
    assert len(committed["proposals"]) == 1, "the committed proposal did not survive the crash"
    assert committed["keys"] == [("worker-call-1", committed["proposals"][0][0])]

    receipt = ok(db, "worker", "wiki_propose", propose_args(base))
    assert receipt["proposal"] == committed["proposals"][0][0]
    assert durable(db) == committed, "retry after a lost reply created new rows"
    assert committed["heads"] == before["heads"] and committed["sequence"] == before["sequence"]

    changed = {**propose_args(base), "markdown": "different payload"}
    code, reply = rpc(db, "worker", "wiki_propose", changed)
    assert code == 1 and reply["kind"] == "error", "a changed payload under the same key was accepted"
    assert durable(db) == committed


# ─── Publication ──────────────────────────────────────────────────────

def test_kill_before_publication_commit_changes_nothing_and_retry_publishes_once(seeded):
    db, base = seeded
    ok(db, "worker", "wiki_propose", propose_args(base))
    before = durable(db)
    decide = {"proposalKey": "worker-call-1", "digest": pending_digest(db, "worker-call-1"), "decision": "publish"}
    crash(db, "curator", "wiki_curator_decide", decide, "publish.before-commit")
    assert durable(db) == before, "a half-published revision became durable"

    outcome = ok(db, "curator", "wiki_curator_decide", decide)
    assert outcome["kind"] == "committed"
    state = durable(db)
    assert state["heads"] == [("page", outcome["page_revision"], "active")]
    assert state["sequence"] == (before["sequence"][0], before["sequence"][1] + 1)
    assert [(r[1], r[2], r[3]) for r in added(before, state, "outbox")] == [(outcome["page_revision"], "index", "pending")]
    assert state["fts"] == [("page", outcome["page_revision"])]
    assert state["operations"] == [("worker-call-1", "worker", "committed")]
    assert len(state["decisions"]) == 1


def test_kill_after_publication_commit_before_reply_retry_is_identical(seeded):
    db, base = seeded
    ok(db, "worker", "wiki_propose", propose_args(base))
    before = durable(db)
    decide = {"proposalKey": "worker-call-1", "digest": pending_digest(db, "worker-call-1"), "decision": "publish"}
    crash(db, "curator", "wiki_curator_decide", decide, "rpc.after-commit-before-reply")
    committed = durable(db)
    new_revision = committed["heads"][0][1]
    assert new_revision != base
    assert committed["sequence"] == (before["sequence"][0], before["sequence"][1] + 1)
    assert committed["fts"] == [("page", new_revision)]
    assert [(r[1], r[3]) for r in added(before, committed, "outbox")] == [(new_revision, "pending")]

    # The review digest is computed from proposal + epoch, so it is still valid.
    outcome = ok(db, "curator", "wiki_curator_decide", decide)
    assert outcome["kind"] == "committed" and outcome["page_revision"] == new_revision
    assert durable(db) == committed, "replaying a committed decision published twice"

    code, reply = rpc(db, "curator", "wiki_curator_decide", {**decide, "decision": "reject", "reason": "late"})
    assert code == 1 and reply["kind"] == "error", "a contradictory decision was accepted after commit"
    assert durable(db) == committed


# ─── Index promotion acknowledgement ──────────────────────────────────

def promotion_args(db):
    store = connect_knowledge(str(db), PROJECT)
    sys.path.insert(0, str(ROOT / "src" / "authority"))
    import retrieval
    captured = retrieval.snapshot(store, PROJECT)
    store.disconnect()
    assert captured["outboxIds"], "publication must have queued index work"
    return {"target": captured["snapshot"], "generation": "gen-test-1", "modelDigest": "m" * 64,
            "outboxIds": captured["outboxIds"]}


def test_kill_before_promotion_ack_commit_keeps_outbox_pending(seeded):
    db, base = seeded
    published(db, base)
    args = promotion_args(db)
    before = durable(db)
    assert before["generations"] == []
    crash(db, "worker", "wiki_index_promoted", args, "promotion.before-commit")
    assert durable(db) == before, "a crashed acknowledgement marked work done"

    assert ok(db, "worker", "wiki_index_promoted", args)["indexedThrough"] == args["target"]
    state = durable(db)
    assert {r[0] for r in state["outbox"] if r[3] == "done"} == set(args["outboxIds"])
    assert state["generations"] == [(PROJECT, "gen-test-1", args["target"]["epoch"], args["target"]["sequence"], "m" * 64)]


def test_kill_after_promotion_ack_commit_retry_is_idempotent(seeded):
    db, base = seeded
    published(db, base)
    args = promotion_args(db)
    crash(db, "worker", "wiki_index_promoted", args, "rpc.after-commit-before-reply")
    committed = durable(db)
    assert {r[0] for r in committed["outbox"] if r[3] == "done"} == set(args["outboxIds"])
    assert len(committed["generations"]) == 1

    assert ok(db, "worker", "wiki_index_promoted", args)["indexedThrough"] == args["target"]
    assert durable(db) == committed


# ─── The hook itself ──────────────────────────────────────────────────

def test_unregistered_fault_name_fails_loudly_without_mutation(seeded):
    db, base = seeded
    before = durable(db)
    code, reply = rpc(db, "worker", "wiki_propose", propose_args(base), fault="propose.typo")
    assert code == 1 and reply["kind"] == "error"
    assert durable(db) == before


def test_every_registered_point_is_placed_exactly_once():
    python = "\n".join(p.read_text() for p in (ROOT / "src").rglob("*.py"))
    typescript = "\n".join(p.read_text() for p in (ROOT / "src").rglob("*.ts"))
    placed = re.findall(r"""faults\.point\(['"]([^'"]+)['"]""", python)
    placed += re.findall(r"""faultPoint\(['"]([^'"]+)['"]\)""", typescript)
    assert sorted(placed) == sorted(faults.POINTS)
    ts_registry = re.search(r"const POINTS = new Set\(\[([^\]]*)\]\)", (ROOT / "src/retrieval/faults.ts").read_text())
    assert sorted(re.findall(r'"([^"]+)"', ts_registry.group(1))) == sorted(re.findall(r"""faultPoint\(['"]([^'"]+)['"]\)""", typescript))
