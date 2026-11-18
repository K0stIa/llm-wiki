"""Transactional, citable LF spans. No model or derived index is authoritative."""
import hashlib
import json
import re

LINES_PER_CHUNK = 32
CANDIDATES = 40
QUESTION_WORDS = frozenset(
    "where which what there about would could should when while their this those these does "
    "using used use your from that have with were will has been are was the and for can how why".split()
)
# Identifier-shaped query tokens: separators inside a word (a.b, a_b, a/b, a-b, a:b), camelCase, letters with digits.
IDENTIFIER = re.compile(r"(?<![\w./-])(?:[A-Za-z_][A-Za-z0-9]*(?:[._/:-][A-Za-z0-9_]+)+|[a-z]+[A-Z][A-Za-z0-9]+"
                        r"|[A-Za-z]+[0-9][A-Za-z0-9]*|[A-Za-z0-9]*_[A-Za-z0-9_]+)(?![\w/-])")
EXACT_MAX_OBJECTS = 1


def exact_identifier_keys(query, documents):
    """Chunk keys that contain an identifier from the query verbatim (case-sensitive, word-bounded), for
    identifiers found in exactly EXACT_MAX_OBJECTS object. A rare exact identifier is strong evidence that
    bm25 over its split word pieces can rank far down."""
    keys = []
    for token in dict.fromkeys(IDENTIFIER.findall(query)):
        if len(token) < 4:
            continue
        pattern = re.compile(r"(?<![\w./-])" + re.escape(token) + r"(?![\w/-])")
        hits = [d for d in documents if pattern.search(d["title"] + "\n" + d["text"])]
        if 0 < len({(d["kind"], d["object"]) for d in hits}) <= EXACT_MAX_OBJECTS:
            keys += [d["key"] for d in hits]
    return list(dict.fromkeys(keys))


def spans(body, first=1, last=None):
    lines = body.split("\n")
    last = len(lines) if last is None else min(last, len(lines))
    for start in range(first, last + 1, LINES_PER_CHUNK):
        end = min(start + LINES_PER_CHUNK - 1, last)
        yield start, end, "\n".join(lines[start - 1:end])


def key_for(item):
    return hashlib.sha256(json.dumps([item[k] for k in ("kind", "object", "revision", "start", "end")],
                                    separators=(",", ":")).encode()).hexdigest()


def insert_chunks(conn, project, kind, object_id, revision, title, body, first=1, last=None):
    digest = "h:" + hashlib.sha256(body.encode()).hexdigest()
    for start, end, text in spans(body, first, last):
        if not text.strip():
            continue
        conn.execute("INSERT INTO retrieval_chunks VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (project, kind, object_id, revision, start, end, digest, title, text,
                      key_for(dict(kind=kind, object=object_id, revision=revision, start=start, end=end))))


def published(conn, project, page, revision, retired=False):
    """Called after the head change, before its publication transaction commits."""
    conn.execute("DELETE FROM retrieval_chunks WHERE project=? AND kind='page' AND object=?", (project, page))
    if not retired:
        title, body = conn.execute("SELECT title,body FROM page_revisions WHERE revision=?", (revision,)).fetchone()
        insert_chunks(conn, project, "page", page, revision, title, body)
    # Recompute eligibility, not a public index of all captured/private evidence.
    conn.execute("DELETE FROM retrieval_chunks WHERE project=? AND kind='source'", (project,))
    seen = set()
    for (citations,) in conn.execute("""SELECT r.citations FROM page_heads h JOIN page_revisions r ON r.revision=h.revision
                                        WHERE h.project=? AND h.state='active'""", (project,)):
        for source in json.loads(citations):
            citation = source.get("citation", source)
            if citation.get("kind") != "source":
                continue
            row = conn.execute("SELECT title,text,hash FROM evidence_revisions WHERE project=? AND revision=?",
                               (project, citation.get("revision"))).fetchone()
            if not row or row[2] != citation.get("hash"):
                continue
            first, last = citation.get("start", 1), citation.get("end", len(row[1].split("\n")))
            if type(first) is not int or type(last) is not int or not 1 <= first <= last <= len(row[1].split("\n")):
                continue
            identity = (citation["revision"], first, last)
            if identity not in seen:
                seen.add(identity)
                insert_chunks(conn, project, "source", citation.get("source", citation["revision"]),
                              citation["revision"], row[0], row[1], first, last)


def snapshot(store, project, query=""):
    conn = store.connect(project)
    conn.execute("BEGIN")
    try:
        identity = conn.execute("SELECT identity FROM authority_identity").fetchone()[0]
        epoch, sequence = conn.execute("SELECT epoch,sequence FROM projects WHERE id=?", (project,)).fetchone()
        names = ("kind", "object", "revision", "start", "end", "hash", "title", "text", "key")
        documents = [dict(zip(names, row)) for row in conn.execute(
            "SELECT kind,object,revision,start,end,hash,title,text,key FROM retrieval_chunks WHERE project=?", (project,))]
        terms = re.findall(r"\w+", query, re.UNICODE)[:64]
        focused = [term for term in terms if len(term) > 2 and term.casefold() not in QUESTION_WORDS]
        match = " OR ".join('"' + term + '"' for term in (focused if len(focused) >= 2 else terms))
        lexical = [r[0] for r in conn.execute(
            "SELECT key FROM retrieval_chunks WHERE retrieval_chunks MATCH ? AND project=? ORDER BY bm25(retrieval_chunks),kind,object,start,key LIMIT ?",
            (match, project, CANDIDATES))] if match else []
        links = {p: re.findall(r"\[\[([^\]|#]+)(?:[^\]]*)\]\]", body)
                 for p, body in conn.execute("""SELECT h.page,r.body FROM page_heads h JOIN page_revisions r ON h.revision=r.revision
                                                WHERE h.project=? AND h.state='active'""", (project,))}
        source_links = {}
        for page, citations in conn.execute("""SELECT h.page,r.citations FROM page_heads h JOIN page_revisions r ON h.revision=r.revision
                                               WHERE h.project=? AND h.state='active'""", (project,)):
            source_links[page] = [s.get("citation", s).get("revision") for s in json.loads(citations)
                                  if s.get("citation", s).get("kind") == "source"]
        outbox = [r[0] for r in conn.execute("SELECT id FROM outbox WHERE project=? AND kind='index' AND status='pending'", (project,))]
        return {"snapshot": {"authority": identity, "project": project, "epoch": epoch, "sequence": sequence},
                "documents": documents, "lexical": lexical, "exact": exact_identifier_keys(query, documents) if query else [],
                "links": links, "sourceLinks": source_links,
                "outboxIds": outbox, "chunkLines": LINES_PER_CHUNK}
    finally:
        conn.rollback()  # release before embedding/model work


def resolve(store, project, args):
    conn = store.connect(project)
    conn.execute("BEGIN")
    try:
        epoch = conn.execute("SELECT epoch FROM projects WHERE id=?", (project,)).fetchone()[0]
        identity = conn.execute("SELECT identity FROM authority_identity WHERE id=1").fetchone()[0]
        if epoch != args["epoch"] or identity != args["authority"]:
            raise ValueError("authority restored during recall")
        result = []
        for item in args["passages"]:
            if item["kind"] == "page":
                row = conn.execute("SELECT body FROM page_revisions WHERE project=? AND page=? AND revision=?",
                                   (project, item["object"], item["revision"])).fetchone()
            else:
                row = conn.execute("SELECT text FROM evidence_revisions WHERE project=? AND revision=?",
                                   (project, item["revision"])).fetchone()
            if not row or "h:" + hashlib.sha256(row[0].encode()).hexdigest() != item["hash"]:
                raise ValueError("immutable citation body changed")
            lines = row[0].split("\n")
            if not 1 <= item["start"] <= item["end"] <= len(lines):
                raise ValueError("invalid citation bounds")
            result.append({**item, "text": "\n".join(lines[item["start"] - 1:item["end"]])})
        return result
    finally:
        conn.rollback()
