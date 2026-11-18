#!/usr/bin/env python3
"""Trusted host-adapter entry point: journaled proposals over the local authority RPC.

    journal_rpc.py JOURNAL DATABASE PROJECT < request.json

Requests (one JSON object on stdin):
  {"op": "enroll"}                                  explicit first enrollment at the live epoch
  {"op": "execute", "session": S, "call": C, "args": {...}}
  {"op": "recover"}                                 replay unfinished calls with their original keys

S and C are the HOST's durable identities (for Pi: session id and tool call id
from the persisted session). They are never model arguments. `args` may not
contain `key` or `expectedEpoch`; the journal derives both.

The journal file holds its own enrolled scope (project, worker, epoch). The
launcher keeps it outside every worker mount. Every execute rechecks the live
authority binding, so a restored authority (new epoch) fails closed instead of
replaying under a fresh key.

Exit 0 with {"kind": "receipt"|"recovered"|"enrolled", ...}; exit 1 with
{"kind": "error", ...}. A crash leaves no reply; the adapter must run
`recover` before accepting new calls.
"""
import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from host_journal import Journal  # noqa: E402
from worker_service import validate  # noqa: E402

RPC = HERE / "authority_rpc.py"


class LocalJournal(Journal):
    """Journal whose transport is the one-shot worker authority RPC process."""

    def __init__(self, path, database, project, epoch):
        super().__init__(path, project=project, principal="worker", epoch=epoch)
        self.database, self.project = database, project

    def send(self, endpoint, request):
        tool, args = validate(request)
        proc = subprocess.run([sys.executable, str(RPC), self.database, self.project, "worker", tool],
                              input=json.dumps(args), capture_output=True, text=True, timeout=60)
        if proc.returncode and not proc.stdout.strip():
            # The authority may or may not have committed. Recovery replays the same key.
            raise ValueError("authority exited without a reply; recover with the journaled key")
        if proc.returncode:
            raise ValueError("authority denied request; no fresh-key retry permitted")
        return {"result": json.loads(proc.stdout)}


def live_epoch(database, project):
    proc = subprocess.run([sys.executable, str(RPC), database, project, "worker", "wiki_host_binding"],
                          input="{}", capture_output=True, text=True, timeout=60)
    if proc.returncode:
        raise ValueError("authority binding unavailable")
    return json.loads(proc.stdout)["epoch"]


def enrolled_scope(path):
    with closing(sqlite3.connect(Path(path).absolute().as_uri() + "?mode=ro", uri=True)) as c:
        project, principal, epoch = json.loads(c.execute("SELECT value FROM scope").fetchone()[0])
    return project, principal, epoch


def handle(journal_path, database, project, request):
    database = str(Path(database).resolve(strict=True))
    op = request.get("op")
    if op == "enroll":
        epoch = live_epoch(database, project)
        Journal.enroll(journal_path, project=project, principal="worker", epoch=epoch)
        return {"kind": "enrolled", "project": project, "epoch": epoch}
    scoped_project, principal, epoch = enrolled_scope(journal_path)
    if scoped_project != project or principal != "worker":
        raise ValueError("journal enrolled for a different scope")
    journal = LocalJournal(journal_path, database, project, epoch)
    if op == "execute":
        if set(request) != {"op", "session", "call", "args"}:
            raise ValueError("execute needs exactly session, call, args")
        reply = journal.execute(None, request["session"], request["call"], request["args"])
        return {"kind": "receipt", "result": reply["result"]}
    if op == "recover":
        done = journal.recover(None)
        return {"kind": "recovered", "calls": [{"session": s, "call": c, "result": r["result"]} for s, c, r in done]}
    raise ValueError("unknown op")


if __name__ == "__main__":
    try:
        if len(sys.argv) != 4:
            raise ValueError("usage: journal_rpc.py JOURNAL DATABASE PROJECT")
        print(json.dumps(handle(*sys.argv[1:], json.load(sys.stdin)), ensure_ascii=False))
    except Exception as error:
        print(json.dumps({"kind": "error", "error": type(error).__name__, "message": str(error)}))
        sys.exit(1)
