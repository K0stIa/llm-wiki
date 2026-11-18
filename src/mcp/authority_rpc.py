"""Private subprocess entry point for the launch-bound stdio MCP server.

Only the local launcher chooses database/project/principal. This is not an
HTTP endpoint. Caller arguments never select a filesystem path or identity.
"""
import base64
import dataclasses
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "authority"))
from authority import connect_knowledge, ChangeKind, DecisionKind
import retrieval
import faults


def lexical_recall(store, project, args):
    cap = args.get("maxBytes", 24000)
    if not 2048 <= cap <= 24000:
        raise ValueError("recall byte cap must be 2048..24000")
    captured = retrieval.snapshot(store, project, args["query"])
    if args.get("coverage") == "require-hybrid-current":
        return {"kind": "not-ready", "reason": "hybrid-unavailable", "snapshot": captured["snapshot"]}
    by_key = {p["key"]: p for p in captured["documents"]}
    selected = [by_key[k] for k in captured["lexical"]]
    rows = retrieval.resolve(store, project, {"authority": captured["snapshot"]["authority"], "epoch": captured["snapshot"]["epoch"], "passages": selected})
    result = {"kind": "context", "coverage": "lexical-only", "snapshot": captured["snapshot"],
              "index": {"kind": "absent"}, "evidence": {"kind": "candidates", "passages": []}}
    for row in rows:
        if len(result["evidence"]["passages"]) == 10:
            break
        passage = {k: row[k] for k in ("revision", "start", "end", "hash", "title", "text")}
        passage["page" if row["kind"] == "page" else "source"] = row["object"]
        result["evidence"]["passages"].append(passage)
        if len(json.dumps(result, ensure_ascii=False).encode()) > cap:
            result["evidence"]["passages"].pop()
    if rows and not result["evidence"]["passages"]:
        return {"kind": "capacity", "reason": "complete-cited-span-does-not-fit", "snapshot": captured["snapshot"]}
    if not rows:
        result["evidence"]["kind"] = "no-matches"
    return result


def review_digest(store, project, proposal_id, payload_digest):
    epoch = store.connect(project).execute('SELECT epoch FROM projects WHERE id=?', (project,)).fetchone()[0]
    bundle = json.dumps([project, epoch, proposal_id, payload_digest], ensure_ascii=False, separators=(',', ':'))
    return 'review:' + hashlib.sha256(bundle.encode('utf-8')).hexdigest()


def dispatch(database, project, principal, tool, args):
    store = connect_knowledge(database, project)
    conn = store.connect(project)
    if tool == "wiki_recall_snapshot":
        return retrieval.snapshot(store, project, args.get("query", ""))
    if tool == "wiki_recall_resolve":
        return retrieval.resolve(store, project, args)
    if tool == "wiki_index_promoted":
        target = args["target"]
        actual = retrieval.snapshot(store, project)["snapshot"]
        if any(target[k] != actual[k] for k in ("authority", "project", "epoch")) or target["sequence"] > actual["sequence"]:
            raise ValueError("invalid indexed target")
        with conn:
            conn.execute("""INSERT INTO retrieval_generations VALUES (?,?,?,?,?,?)
                ON CONFLICT(project) DO UPDATE SET generation=excluded.generation,authority=excluded.authority,
                epoch=excluded.epoch,sequence=excluded.sequence,model_digest=excluded.model_digest
                WHERE retrieval_generations.epoch!=excluded.epoch OR retrieval_generations.sequence<=excluded.sequence""",
                (project, args["generation"], target["authority"], target["epoch"], target["sequence"], args["modelDigest"]))
            for item in args["outboxIds"]:
                conn.execute("UPDATE outbox SET status='done' WHERE id=? AND project=? AND kind='index'", (item, project))
            faults.point("promotion.before-commit")
        return {"indexedThrough": target}
    if tool.startswith("wiki_curator_") and principal != "curator":
        raise PermissionError("curator principal required")
    if tool in ("wiki_page", "wiki_read"):
        if args.get("revision"):
            row = conn.execute(
                "SELECT 1 FROM page_revisions WHERE project=? AND page=? AND revision=?",
                (project, args["page"], args["revision"]),
            ).fetchone()
            if not row:
                raise LookupError("revision not found in bound project/page")
        return dataclasses.asdict(store.page(project, args["page"], args.get("revision")))
    if tool == 'wiki_host_binding':
        return {'project':project,'principal':principal,'epoch':store._get_epoch(project)}
    if tool in ('wiki_propose','wiki_host_propose'):
        expected_epoch = args['expectedEpoch'] if tool == 'wiki_host_propose' else None
        if tool == 'wiki_host_propose' and (not isinstance(expected_epoch,str) or not expected_epoch):
            raise ValueError('expected epoch required')
        if principal == 'curator':
            raise PermissionError('curator cannot propose')
        if args.get('key') and conn.execute("SELECT 1 FROM operations WHERE project=? AND op_key=? AND status='failed'", (project, args['key'])).fetchone():
            raise PermissionError('operation key is invalidated; do not replay a pre-restore mutation')
        receipt = store.propose(project, args["page"], args["baseRevision"],
                                ChangeKind(args["changeKind"]), args["title"], args["markdown"],
                                principal, args.get("sources", []), key=args.get("key"), expected_epoch=expected_epoch)
        return dataclasses.asdict(receipt) if receipt else {"kind": "conflict"}
    if tool == "wiki_operation":
        row = conn.execute("SELECT principal FROM operations WHERE project=? AND op_key=?",
                           (project, args["key"])).fetchone()
        if not row or (row[0] != principal and principal != "curator"):
            return {"kind": "unknown"}
        return store.operation(project, args["key"])
    if tool == "wiki_curator_pending":
        limit = args.get('limit', 20)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('limit must be 1..100')
        epoch = store._get_epoch(project)
        cutoff = conn.execute('SELECT COALESCE(MAX(rowid),0) FROM proposals WHERE project=?', (project,)).fetchone()[0]
        after = 0
        if args.get('cursor') is not None:
            token = json.loads(base64.urlsafe_b64decode(args['cursor']).decode())
            if not isinstance(token, list) or len(token)!=4 or token[:2]!=[project,epoch] or any(type(x) is not int for x in token[2:]) or not 0 <= token[2] <= token[3] <= cutoff:
                raise ValueError('invalid or stale-epoch proposal cursor')
            after, cutoff = token[2:]
        rows = conn.execute("""
            SELECT proposal_id,rowid FROM proposals WHERE project=? AND state IN ('pending','blocked') AND rowid>? AND rowid<=?
            ORDER BY rowid LIMIT ?
        """, (project, after, cutoff, limit+1)).fetchall()
        next_cursor = base64.urlsafe_b64encode(json.dumps([project,epoch,rows[limit-1][1],cutoff]).encode()).decode() if len(rows)>limit else None
        items = [store.read_proposal(project, row[0]) for row in rows[:limit]]
        for item in items:
            item['reviewDigest'] = review_digest(store, project, item['id'], item['digest'])
        return {"items": items, "next": next_cursor}
    if tool == "wiki_curator_decide":
        row = conn.execute("""
            SELECT p.payload_digest,p.proposal_id,p.actor FROM proposals p JOIN proposal_keys k ON k.proposal_id=p.proposal_id
            WHERE k.key=? AND k.project=? AND p.project=?
        """, (args["proposalKey"], project, project)).fetchone()
        if row and row[2] == principal:
            raise PermissionError('curator cannot decide its own proposal')
        if args.get("decision") == "reject" and args.get("digest") is None:
            return dataclasses.asdict(store.reject_metadata(project, args["proposalKey"], args.get("reason") or "rejected"))
        if not row or review_digest(store, project, row[1], row[0]) != args.get("digest"):
            raise PermissionError("proposal review digest does not match bound project")
        return dataclasses.asdict(store.decide(project, args["proposalKey"],
                                              DecisionKind(args["decision"]), args.get("reason")))
    if tool == "wiki_recall":
        return lexical_recall(store, project, args)
    raise ValueError("unknown tool")


if __name__ == "__main__":
    try:
        database, project, principal, tool = sys.argv[1:]
        if principal not in ("worker", "curator"):
            raise PermissionError("invalid launch principal")
        result = dispatch(database, project, principal, tool, json.load(sys.stdin))
        faults.point("rpc.after-commit-before-reply", tool)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        print(json.dumps({"kind": "error", "error": type(error).__name__, "message": str(error)}))
        sys.exit(1)
