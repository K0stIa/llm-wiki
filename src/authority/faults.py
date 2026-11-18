"""Named crash points for durability tests (G1 "kill at named boundaries").

`point(name)` terminates the process immediately (os._exit, no cleanup, no
SQLite commit/rollback, no reply) when the trusted launcher set
WIKI_TEST_FAULT_POINT to exactly that name. The variable is process
environment chosen by whoever launches the service; it is never request data,
and the MCP/worker layers never accept it as an argument.

Unknown names fail loudly so a typo cannot make a crash test pass vacuously:
a test asserts the process exited with FAULT_EXIT, proving the point ran.
"""
import os
import sys

ENV = "WIKI_TEST_FAULT_POINT"
FAULT_EXIT = 97

POINTS = frozenset({
    # Authority (src/authority/authority.py), inside the open transaction.
    "propose.before-commit",
    "publish.before-commit",
    # RPC process (src/mcp/authority_rpc.py), after dispatch returned/committed.
    "rpc.after-commit-before-reply",
    # Index acknowledgement (wiki_index_promoted), inside its transaction.
    "promotion.before-commit",
    # Trusted host journal (src/mcp/host_journal.py), used by src/mcp/journal_rpc.py.
    "journal.after-prepare",
    "journal.after-send",
    "journal.after-receipt",
    # Derived-index builder (src/retrieval/qmd-integration.ts via faults.ts).
    # Listed here so the Python RPC children it spawns accept the variable.
    "generation.after-stage",
    "generation.after-rename",
    "generation.after-pointer",
})


def point(name: str, scope: str | None = None) -> None:
    """Crash here if the launcher selected `name`, or `name:scope` (e.g. one RPC tool)."""
    if name not in POINTS:
        raise AssertionError(f"unregistered fault point {name!r}")
    wanted = os.environ.get(ENV)
    if not wanted:
        return
    if wanted.split(":", 1)[0] not in POINTS:
        raise AssertionError(f"{ENV}={wanted!r} is not a registered fault point")
    if wanted == name or (scope is not None and wanted == f"{name}:{scope}"):
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(FAULT_EXIT)
