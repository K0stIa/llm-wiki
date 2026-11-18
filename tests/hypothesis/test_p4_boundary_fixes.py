"""P4 boundary-fix verification tests.

Validates the 6 concrete P4 fixes from the code review:
  1. registerWikiTools uses registerTool(toolDef), not registerTool(name, handler)
  2. Bridge uses JSON file args, not shell interpolation
  3. execAuthority returns the actual result, not the store object
  4. WikiService.principal is a bound property (FIX #4) — no escalation
  5. verifyBoundary correctly rejects errors (FIX #5)
  6. runChildAgentWithWiki returns unverified for child execution (FIX #6)

Note: src/mcp/transport.ts and src/authority/bridge.ts are TypeScript.
Python tests verify the Python authority layer that both wrap.
TS boundary fixes are verified by checking source file content.
"""
import os
import sys
import tempfile
from typing import Any

import pytest
from hypothesis import given, settings, strategies as st

from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.authority.authority import connect_knowledge, NotFoundError, ChangeKind


# ─── FIX #4: WikiService principal is a bound property (verified via source) ─

def test_wiki_service_principal_is_bound_not_callable():
    """WikiService.principal is a bound property. No caller can escalate.

    Verified by checking transport.ts source:
    - isAuthorized(toolName) takes NO principal arg
    - callTool(toolName, args) takes NO principal arg
    - createWikiService(dbPath, project, principal) binds principal
    """
    transport_path = ROOT / "src/mcp/transport.ts"
    with open(transport_path) as f:
        source = f.read()

    # isAuthorized should NOT take a principal parameter
    assert "isAuthorized(toolName: string, principal?" not in source
    # callTool should NOT take a principal parameter
    assert "callTool(toolName: string, args: object, principal" not in source
    # principal should be a readonly property
    assert "readonly principal: string" in source
    # The implementation should use this.principal, not a caller arg
    assert "this.principal" in source
    # No escalation path: worker service cannot be made curator
    assert "principal !== \"curator\"" in source


def test_worker_service_cannot_call_curator():
    """Worker WikiService rejects curator tools via bound principal.

    Verified by checking transport.ts source:
    - CURATOR_TOOL_NAMES check uses this.principal
    - No way to pass a different principal at call time
    """
    transport_path = ROOT / "src/mcp/transport.ts"
    with open(transport_path) as f:
        source = f.read()

    # The authorization check uses bound principal
    assert "this.principal !== \"curator\"" in source
    # No escape hatch: isAuthorized(toolName) has no caller arg
    assert "isAuthorized(toolName: string): boolean" in source
    # No escape hatch: callTool(toolName, args) has no caller principal
    assert "callTool(toolName: string, args: object): Promise" in source


def test_two_projects_get_two_services():
    """Two projects → two WikiService instances (no singleton reuse).

    Verified by checking transport.ts source:
    - createWikiService(dbPath, project, principal) creates fresh instance
    - No module-level singleton
    """
    transport_path = ROOT / "src/mcp/transport.ts"
    with open(transport_path) as f:
        source = f.read()

    # No singleton pattern (_wikiService global)
    assert "let _wikiService" not in source
    # Each createWikiService creates a new server instance
    assert "createMCPServer(dbPath, project, principal)" in source
    # Principal is passed to createWikiService, not defaulted from caller
    assert "principal: string = \"worker\"" in source or "principal: string =" in source


# ─── FIX #3: execAuthority returns actual result, not store object ──────

def test_bridge_page_returns_page_not_store():
    """Python authority page() returns PageSnapshot (not KnowledgeStore).

    The bridge wraps this same function. If the bridge returned the store
    (not the result), page() would return a KnowledgeStore object.
    We verify the Python layer returns a proper PageSnapshot.
    """
    db = tempfile.mktemp(suffix=".db")
    store = connect_knowledge(db, "proj-test")
    store.create_page("proj-test", "test-page", "Title", "test body", "worker")

    result = store.page("proj-test", "test-page")
    assert result is not None
    assert result.page == "test-page"
    assert result.markdown == "test body"
    assert result.state == "active"
    assert hasattr(result, "hash")  # PageSnapshot has hash
    # NOT a store (which would have no .page as string)
    assert type(result.page) is str


def test_bridge_propose_returns_receipt_not_store():
    """Python authority propose() returns ProposalReceipt (not store).

    The bridge delegates to this same function. If it returned the store,
    propose() would return a KnowledgeStore object.
    """
    db = tempfile.mktemp(suffix=".db")
    store = connect_knowledge(db, "proj-test")
    store.create_page("proj-test", "test-propose", "Title", "body", "worker")
    conn = store.connect("proj-test")
    row = conn.execute(
        "SELECT revision FROM page_heads WHERE project=? AND page=?",
        ("proj-test", "test-propose"),
    ).fetchone()
    head = row[0]
    # conn stays open; propose() uses its own connection

    receipt = store.propose("proj-test", "test-propose", head, ChangeKind.REPLACE,
                            "Title v1", "body v1", "worker", [])
    assert receipt is not None
    # receipt is a ProposalReceipt dataclass, not a store
    assert hasattr(receipt, "key")
    assert hasattr(receipt, "kind")
    assert hasattr(receipt, "proposal")
    assert hasattr(receipt, "digest")
    assert receipt.kind == "pending"
    # NOT a store (which would have .connect method)
    assert not hasattr(receipt, "connect")


def test_bridge_decide_returns_decision_not_store():
    """Python authority decide() returns DecisionOutcome (not store)."""
    db = tempfile.mktemp(suffix=".db")
    store = connect_knowledge(db, "proj-test")
    store.create_page("proj-test", "test-decide", "Title", "body", "worker")
    conn = store.connect("proj-test")
    row = conn.execute(
        "SELECT revision FROM page_heads WHERE project=? AND page=?",
        ("proj-test", "test-decide"),
    ).fetchone()
    head = row[0]


    receipt = store.propose("proj-test", "test-decide", head, ChangeKind.REPLACE,
                            "Title v1", "body v1", "worker", [])
    assert receipt is not None
    # decide returns a DecisionOutcome dataclass, not a store
    outcome = store.decide("proj-test", receipt.key, "publish")
    assert outcome is not None
    conn.close()
    assert outcome.kind == "committed"
    assert hasattr(outcome, "page_revision")
    assert hasattr(outcome, "project_revision")
    # NOT a store
    assert not hasattr(outcome, "connect")


# ─── FIX #5: verifyBoundary correctly rejects errors ───────────────────

def test_verify_boundary_passes_on_success():
    """Boundary test: creates a page in a fresh DB, verifies it's readable."""
    db = tempfile.mktemp(suffix=".db")
    store = connect_knowledge(db, "boundary-test")
    store.create_page("boundary-test", "boundary-page", "Boundary", "body", "worker")
    # Verify the page is actually stored (boundary works)
    result = store.page("boundary-test", "boundary-page")
    assert result is not None
    assert result.page == "boundary-page"
    assert result.markdown == "body"


def test_verify_boundary_rejects_error():
    """Source guard complements real success/failure runs in test_bridge_recovery_runtime."""
    bridge_path = ROOT / "src/authority/bridge.ts"
    with open(bridge_path) as f:
        source = f.read()
    assert 'created.kind !== "page"' in source
    assert 'read.kind === "page"' in source
    assert 'read.hash === created.hash' in source


# ─── FIX #2: Bridge uses JSON file args (no shell interpolation) ───────

def test_bridge_no_shell_interpolation():
    """Use fixed Python entrypoint, argument-vector spawn, and data-only JSON file.

    Hostile strings and subprocess faults are also exercised through the real boundary.
    """
    bridge_path = ROOT / "src/authority/bridge.ts"
    with open(bridge_path) as f:
        source = f.read()
    assert 'spawnSync("python3", [rpc, argFile]' in source
    assert 'writeFileSync(argFile, JSON.stringify(' in source
    assert 'execSync' not in source
    assert 'cmdFile' not in source
    assert 'default=str' not in (ROOT/'src/authority/bridge_rpc.py').read_text()


# ─── FIX #1: registerWikiTools uses registerTool(toolDef) ───────────────

def test_register_tool_signature():
    """Pi's registerTool takes ToolDefinition (not name, handler).

    Verified from installed Pi SDK @earendil-works/pi-coding-agent:
    registerTool<T>(tool: ToolDefinition<T>): void

    Old pi-integration.ts called: pi.registerTool(def.name, toolDef) — wrong.
    Fixed: pi.registerTool(toolDef) — correct.
    """
    pi_path = ROOT / "src/pi/pi-integration.ts"
    with open(pi_path) as f:
        source = f.read()

    # Should use registerTool(toolDef) — single arg
    assert "pi.registerTool(toolDef)" in source
    # Should NOT use registerTool(name, toolDef) — two args
    assert "pi.registerTool(def.name, toolDef)" not in source
    # Should NOT use registerTool(name, handler)
    assert "pi.registerTool(def.name," not in source


# ─── FIX #6: runChildAgentWithWiki returns unverified for child execution ─

def test_run_child_agent_returns_unverified():
    """runChildAgentWithWiki documents that child execution requires Pi session.

    G4: \"Launch the host's actual deployed child mechanism. Assert the child
    can see and call the read/propose tools, rather than trusting a parent
    summary.\"

    The function registers the subagent tool and configures tool activation,
    but the actual child execution (child calling wiki tools) requires a live
    Pi session where the parent model invokes the \"subagent\" tool.
    """
    pi_path = ROOT / "src/pi/pi-integration.ts"
    with open(pi_path) as f:
        source = f.read()

    # Should document that child execution requires Pi session
    assert "child execution requires" in source.lower() or "requires live Pi" in source.lower()
    # Should NOT claim verification of child execution
    assert "child execution verified" not in source.lower()
    # Should document the wiring (not execution)
    assert "wiring complete" in source.lower() or "document the WIRING" in source.lower()


# ─── G4: Two-project negative (concrete) ───────────────────────────────

@given(st.integers(min_value=1, max_value=3))
@settings(max_examples=10)
def test_cross_project_negative(n: int):
    """proj-A store cannot access proj-B pages (G4 cross-project).

    This validates the Python authority layer's project scoping.
    The WikiService (TS) wraps this same layer.
    """
    db = tempfile.mktemp(suffix=".db")
    store_a = connect_knowledge(db, "proj-a")
    store_a.create_page("proj-a", "proj-a-secret", "Title", "secret", "worker")

    # proj-b store cannot read proj-a page
    store_b = connect_knowledge(db, "proj-b")
    try:
        result = store_b.page("proj-b", "proj-a-secret")
        assert False, "Cross-project read should have raised NotFoundError"
    except NotFoundError:
        pass  # expected: page not in proj-b's page_heads


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
