"""G1: kill the derived-index builder before and after the generation swap.

DELIVERY G1: "Kill the service at named boundaries ... before/after index
promotion. Restart and retry. Verify receipts, heads, FTS and outbox from
durable state."

The builder is the real src/retrieval/qmd-integration.ts with the approved
cached embedding model, driven through tests/runtime/retrieval-client.mjs.
WIKI_TEST_FAULT_POINT makes it exit 97 at exactly one point; no finally block
runs, so the files on disk are exactly what a crash would leave.

  generation.after-stage    staging + manifest written, nothing promoted
  generation.after-rename   generation directory in place, pointer not swapped
  generation.after-pointer  pointer swapped, authority outbox not acknowledged
"""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.tier_b

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.authority.authority import ChangeKind, DecisionKind, connect_knowledge  # noqa: E402

FAULT_EXIT = 97


class Driver:
    def __init__(self, fault=None):
        env = {k: v for k, v in os.environ.items() if k != "WIKI_TEST_FAULT_POINT"}
        if fault:
            env["WIKI_TEST_FAULT_POINT"] = fault
        self.proc = subprocess.Popen(["node", "node_modules/tsx/dist/cli.mjs", "tests/runtime/retrieval-client.mjs"],
                                     cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, env=env)

    def request(self, action, **kwargs):
        self.proc.stdin.write(json.dumps({"action": action, **kwargs}) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        return json.loads(line) if line else None

    def call(self, action, **kwargs):
        result = self.request(action, **kwargs)
        assert result and result["ok"], result
        return result["value"]

    def close(self):
        self.proc.stdin.close()
        assert self.proc.wait(timeout=60) == 0


@pytest.fixture
def system(tmp_path):
    model = os.environ.get("WIKI_TEST_CACHED_MODEL")
    assert model and Path(model).is_file(), "explicit approved cached model required; downloads are forbidden"
    db = tmp_path / "authority.db"
    store = connect_knowledge(str(db), "a")
    page = store.create_page("a", "engine", "Engine", "The amber engine uses a sapphire coolant pump.", "owner")
    binding = dict(database=str(db), project="a", indexRoot=str(tmp_path / "indexes"), model=model)
    yield store, page, binding, db
    store.disconnect()


def publish(store, page, body):
    receipt = store.propose("a", page.page, page.revision, ChangeKind.REPLACE, "Engine", body, "worker", [])
    assert store.decide("a", receipt.key, DecisionKind.PUBLISH).kind == "committed"


def root_of(binding):
    project_dirs = list(Path(binding["indexRoot"]).iterdir())
    assert len(project_dirs) == 1
    return project_dirs[0]


def files(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file() and "runtime-cache" not in p.parts and "leases" not in p.parts}


def durable(db):
    with sqlite3.connect(db) as c:
        return {"sequence": c.execute("SELECT sequence FROM projects WHERE id='a'").fetchone()[0],
                "generation": c.execute("SELECT generation,sequence FROM retrieval_generations WHERE project='a'").fetchone(),
                "pending": c.execute("SELECT COUNT(*) FROM outbox WHERE project='a' AND kind='index' AND status='pending'").fetchone()[0]}


def recall(binding, coverage="best-available"):
    d = Driver()
    try:
        return d.call("recall", binding=binding, input=dict(query="sapphire coolant pump", coverage=coverage))
    finally:
        d.close()


@pytest.mark.parametrize("point", ["generation.after-stage", "generation.after-rename", "generation.after-pointer"])
def test_builder_crash_around_generation_swap_is_safe_and_recoverable(system, point):
    store, page, binding, db = system
    first = Driver()
    gen1 = first.call("build", binding=binding)
    first.close()
    root = root_of(binding)
    assert (root / "current").read_text().strip() == gen1["generation"]
    before_files = files(root / gen1["generation"])

    publish(store, page, "The amber engine now uses a ruby coolant pump.")
    authority = durable(db)
    assert authority["pending"] >= 1 and authority["generation"] == (gen1["generation"], gen1["target"]["sequence"])

    crashing = Driver(fault=point)
    assert crashing.request("build", binding=binding) is None, "builder replied despite the crash"
    assert crashing.proc.wait(timeout=60) == FAULT_EXIT, f"{point} was not reached"

    # Durable authority state: the acknowledgement never ran.
    assert durable(db) == authority
    current = (root / "current").read_text().strip()
    leftovers = sorted(p.name for p in root.iterdir() if p.name.startswith((".build-", ".pointer-")))
    others = sorted(p.name for p in root.iterdir() if p.name.startswith("g-") and p.name not in (gen1["generation"], current))
    # The previous generation is never mutated by a crashed build.
    assert files(root / gen1["generation"]) == before_files

    if point == "generation.after-pointer":
        # The new generation is complete and current; only bookkeeping lags.
        assert current != gen1["generation"]
        manifest = json.loads((root / current / "manifest.json").read_text())
        assert manifest["target"]["sequence"] == authority["sequence"]
        assert recall(binding, "require-hybrid-current")["coverage"] == "hybrid-current"
        assert leftovers == [] and others == []
    else:
        # Readers keep the old generation and say so; strict callers are refused.
        assert current == gen1["generation"]
        assert recall(binding)["coverage"] == "hybrid-stale"
        assert recall(binding, "require-hybrid-current")["kind"] == "not-ready"
        if point == "generation.after-stage":
            assert len(leftovers) == 1 and leftovers[0].startswith(".build-") and others == []
        else:
            assert leftovers == [] and len(others) == 1

    # Restart: cleanup reclaims the crashed builder's debris but never the current generation.
    d = Driver()
    removed = d.call("cleanup", binding=binding)
    assert (root / current).is_dir()
    assert set(leftovers) | set(others) <= set(removed)
    assert not any(p.name.startswith((".build-", ".pointer-")) for p in root.iterdir())

    # Retry the build: promotion completes and the outbox is acknowledged exactly up to the target.
    gen2 = d.call("build", binding=binding)
    d.close()
    after = durable(db)
    assert (root / "current").read_text().strip() == gen2["generation"]
    assert after["generation"] == (gen2["generation"], authority["sequence"]) and after["pending"] == 0
    assert after["sequence"] == authority["sequence"]
    assert recall(binding, "require-hybrid-current")["coverage"] == "hybrid-current"
