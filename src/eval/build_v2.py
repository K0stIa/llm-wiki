#!/usr/bin/env python3
"""Build evaluation set v2 from the Pi LLM Wiki (see specs/wiki-system/EVAL-V2.md).

CONFIDENTIAL DATA: page text and everything derived from it stays under
.cache/eval/v2/ and goes only to the local approved endpoint. This program
prints counts and hashes only, never text. Do not add prints of content.

    python3 src/eval/build_v2.py select|generate|suggest|codex-judge|fable-judge|opus-judge|fable-deep|delegate-labels|label-page|freeze|status
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path.home() / ".pi" / "agent" / "llm-wiki" / "wiki"
WORK = ROOT / ".cache" / "eval" / "v2"
MANIFEST = ROOT / "research" / "eval-corpus" / "frozen" / "v2" / "manifest.json"
SEED = "eval-v2-2026-11-15"
ENDPOINT = "http://127.0.0.1:8080/v1/chat/completions"
MODEL = "qwen3.8-35b-a3b-mtp-32k"
QUOTAS = {
    "identifier_exact": 40, "paraphrase": 50, "cross_language_ukrainian": 50, "multi_page": 50,
    "superseded_decision": 50, "cross_project_lookalike": 50, "child_written_fact": 50,
    "missing_control": 30, "conflict_control": 20,
}
CONTROLS = {"missing_control", "conflict_control"}
MAX_ATTEMPTS_PER_SLICE = 4  # x quota; exhausting it is recorded, never silently shrunk
THRESHOLDS = {  # DECISIONS.md D2, frozen before measurement
    "evidence_recall_at_10": 0.95, "all_evidence_at_10_multi_page": 0.90,
    "hard_slice_recall_at_10": {"paraphrase": 0.90, "cross_language_ukrainian": 0.90},
    "answers_correct_supported": 0.90, "citation_resolution": 1.0,
    "unsupported_confident_on_controls_max": 0.05, "cross_project_disclosures": 0,
    "superseded_as_current": 0, "context_bytes_max": 24000,
    "warm_recall_p95_seconds": 8.0, "visibility_p95_seconds": 30.0, "rss_max_bytes": 2 * 1024 ** 3,  # warm recall: D11 (was 2.0)
}

STOP = set("""the and that this with from have will would could should about there their which when what
where your into them they then than also been were more most such only other some these those very just
over under after before because while does did done using used use""".split())


# ─── helpers ──────────────────────────────────────────────────────────

def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def order_key(*parts: str) -> str:
    return sha(SEED + "\x00" + "\x00".join(parts))


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9_-]{3,}", text.lower()) if w not in STOP}


def cyrillic_share(text: str) -> float:
    letters = re.findall(r"[A-Za-z\u0400-\u04FF]", text)
    return sum(1 for c in letters if "\u0400" <= c <= "\u04FF") / max(1, len(letters))


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True))
    tmp.replace(path)


# ─── select ───────────────────────────────────────────────────────────

def parse_page(path: Path) -> dict | None:
    text = path.read_text(errors="replace")
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    meta, body = (match.group(1), match.group(2)) if match else ("", text)
    field = lambda k: (re.search(rf"^{k}:\s*(.+)$", meta, re.M) or [None, None])[1]  # noqa: E731
    slug = (field("slug") or path.stem).strip().strip("\"'")
    tags = re.findall(r"[\w-]+", field("tags") or "")
    links = sorted({l.split("|")[0].split("#")[0].strip() for l in re.findall(r"\[\[([^\]]+)\]\]", body)})
    return {"id": slug, "path": str(path.relative_to(SOURCE)), "type": (field("type") or "").strip(),
            "title": (field("title") or slug).strip().strip("\"'"), "tags": tags, "links": links, "body": body.strip()}


def edit_ok(slice_name: str, old: str, new: str, changed: str) -> bool:
    """A supersede edit must really remove the old text (it can re-form at the boundary)."""
    return slice_name != "superseded_decision" or norm(old) not in norm(changed)


def item_still_valid(q: dict, other_bodies: list[str] = ()) -> bool:
    """A superseded span must be gone from the edited page and absent from every other current body
    (normalized); otherwise "superseded fact shown as current" cannot be told from a common phrase."""
    if q["slice"] == "superseded_decision":
        e = next(x for x in q["edits"] if x["kind"] == "supersede")
        span = norm(q["superseded_span"])
        return span not in norm(e["body"]) and not any(span in b for b in other_bodies)
    return True


def current_bodies(pages: list, accepted: list) -> dict[str, str]:
    """Normalized current body per (project, page) once every accepted edit is applied."""
    bodies = {("main", p["id"]): p["body"] for p in pages}
    for q in accepted:
        for e in q["edits"]:
            bodies[(e.get("project", "main") if e["kind"] != "lookalike" else "lookalike", e["page"])] = e["body"]
    return {k: norm(v) for k, v in bodies.items()}


def item_valid_in(q: dict, bodies: dict) -> bool:
    """Validity against the final corpus: the item's own edit must be the page's final body, and its
    superseded span must be absent from that body and from every other current body."""
    own = {("main", e["page"]) for e in q["edits"] if e["kind"] == "supersede"}
    if any(bodies.get(k) != norm(e["body"]) for k, e in zip(sorted(own), [x for x in q["edits"] if x["kind"] == "supersede"])):
        return False
    return item_still_valid(q, [b for k, b in bodies.items() if k not in own])


def settle_valid(pages: list, items: list) -> tuple[list, list]:
    """Drop invalid items until the retained set is stable: dropping one item's edit restores that page's
    original body, which can bring another item's old text back."""
    keep, dropped = list(items), []
    while True:
        bodies = current_bodies(pages, keep)
        bad = {q["id"] for q in keep if not item_valid_in(q, bodies)}
        if not bad:
            return keep, dropped
        dropped += [q for q in keep if q["id"] in bad]
        keep = [q for q in keep if q["id"] not in bad]


def cmd_revalidate(_args) -> None:
    """Drop accepted items that fail rules added after generation; counted as rejections."""
    gen = Generator()
    gen.accepted, dropped = settle_valid(gen.pages, gen.accepted)
    for q in dropped:
        gen.rejected[f"{q['slice']}:old-text-survives"] += 1
    gen.save()
    print(f"dropped={dict(Counter(q['slice'] for q in dropped))}")


def cmd_flag_ambiguous(_args) -> None:
    """Flag accepted lookalike items whose gold span also occurs on another main page and that have no label yet,
    so a judge decides extra gold pages or rejection (D13). Never touches labeled items."""
    gen = Generator()
    labels_path = WORK / "labels.json"
    labels = json.loads(labels_path.read_text()) if labels_path.exists() else {}
    flagged = Counter()
    for q in gen.accepted:
        if q["slice"] != "cross_project_lookalike" or q["needs_label"] or q["id"] in labels:
            continue
        if any(gen.elsewhere(g["span"] or "", [x["page"] for x in q["gold"]], LOOKALIKE_MIN_SPAN) for g in q["gold"]):
            q["needs_label"] = True
            flagged[q["slice"]] += 1
    gen.save()
    print(f"flagged={dict(flagged)}")


def cmd_select(_args) -> None:
    pages, seen = [], Counter()
    for path in sorted(SOURCE.rglob("*.md")):
        page = parse_page(path)
        seen[page["id"]] += 1
        pages.append(page)
    for page in pages:  # disambiguate colliding slugs deterministically
        if seen[page["id"]] > 1:
            page["id"] = f"{page['id']}--{sha(page['path'])[:8]}"
    stems = {Path(p["path"]).stem: p["id"] for p in pages}
    ids = {p["id"] for p in pages}
    for page in pages:
        page["links"] = sorted({l if l in ids else stems[l] for l in page["links"] if l in ids or l in stems} - {page["id"]})
        page["eligible"] = 200 <= len(page["body"].encode()) <= 8000
        page["order"] = order_key("page", page["id"])
    write_json(WORK / "pages.json", pages)
    print(f"pages={len(pages)} eligible={sum(p['eligible'] for p in pages)} "
          f"with_links={sum(bool(p['links']) for p in pages)} source_sha={sha(''.join(p['body'] for p in pages))[:16]}")


# ─── local model ──────────────────────────────────────────────────────

class LocalModel:
    def __init__(self):
        self.path = WORK / "llm-cache.jsonl"
        self.cache = {r["key"]: r["response"] for r in read_jsonl(self.path)}
        self.calls = 0

    def __call__(self, system: str, user: str) -> dict | None:
        payload = {"model": MODEL, "temperature": 0, "seed": 7, "max_tokens": 1024,
                   "chat_template_kwargs": {"enable_thinking": False}, "response_format": {"type": "json_object"},
                   "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        key = sha(json.dumps(payload, sort_keys=True, ensure_ascii=False))
        if key not in self.cache:
            request = urllib.request.Request(ENDPOINT, json.dumps(payload).encode(), {"Content-Type": "application/json"})
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(request, timeout=300) as reply:
                        content = json.load(reply)["choices"][0]["message"]["content"]
                    break
                except Exception:  # noqa: BLE001 - never echo content
                    if attempt == 2:
                        raise SystemExit("local endpoint failed 3 times")
                    time.sleep(5)
            self.cache[key] = content
            with self.path.open("a") as f:
                f.write(json.dumps({"key": key, "response": content}, ensure_ascii=False) + "\n")
            self.calls += 1
        try:
            value = json.loads(self.cache[key])
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None


PROMPTS = {
    "identifier_exact": "You write retrieval evaluation questions. Given a wiki page and an IDENTIFIER that appears in it, "
        "write one natural question a developer would ask that contains the identifier verbatim and is answered by the page. "
        "Return JSON {\"question\": str, \"answer\": str, \"span\": str} where span is an exact substring of the page (20-300 chars) that answers it.",
    "paraphrase": "You write hard retrieval evaluation questions. Given a wiki page, write one question answered by a single passage, "
        "using different words than the page (synonyms, rephrasing; do not copy distinctive terms). "
        "Return JSON {\"question\": str, \"answer\": str, \"span\": str} where span is an exact substring of the page (20-300 chars).",
    "cross_language_ukrainian": "You write cross-language retrieval evaluation questions. Given an English wiki page, write one question "
        "IN UKRAINIAN that a Ukrainian-speaking developer would ask and that the page answers. Keep code identifiers as-is. "
        "Return JSON {\"question\": str (Ukrainian), \"answer\": str (English), \"span\": str} where span is an exact substring of the page (20-300 chars).",
    "multi_page": "You write multi-document evaluation questions. Given PAGE A and PAGE B, write one question whose complete answer needs "
        "one fact from A and one fact from B. Return JSON {\"question\": str, \"answer\": str, \"span_a\": str, \"span_b\": str} "
        "where span_a is an exact substring of PAGE A and span_b an exact substring of PAGE B (20-300 chars each). "
        "If no such question is natural, return {\"skip\": true}.",
    "superseded_decision": "You create a realistic update to a wiki page. Pick one concrete fact (a value, choice, version, setting or decision) "
        "and state how it changed later. Return JSON {\"old_span\": str, \"new_span\": str, \"question\": str, \"answer\": str} where old_span is "
        "an exact substring of the page (10-200 chars), new_span is its replacement text with a different concrete value, and question asks "
        "for the CURRENT value without quoting either span.",
    "cross_project_lookalike": "You create a near-copy of a wiki page for a DIFFERENT project. Pick one concrete fact and change its value. "
        "Return JSON {\"old_span\": str, \"new_span\": str, \"question\": str, \"answer\": str} where old_span is an exact substring of the page "
        "(10-200 chars), new_span replaces it in the copy, and question asks for that fact (answer = the ORIGINAL page's value).",
    "child_written_fact": "You are a child coding agent that just read this wiki page and records a short follow-up note for other agents. "
        "Write a note (3-8 sentences) that summarizes the relevant point and adds ONE new concrete decision or finding not stated in the page, "
        "in a sentence starting with 'Decision:'. Return JSON {\"title\": str, \"note\": str, \"decision\": str, \"question\": str, \"answer\": str} "
        "where decision is the exact 'Decision:' sentence from the note and question asks about it without quoting it.",
    "missing_control": "You write negative evaluation questions. Given a wiki page, write one plausible question about the same subject whose "
        "answer is NOT stated anywhere in the page (a detail a developer might expect but the page lacks). "
        "Return JSON {\"question\": str, \"why_absent\": str}.",
    "conflict_control": "You create a contradicting wiki page. Pick one concrete fact from the page and write a short separate page (2-5 sentences) "
        "on the same subject that states a DIFFERENT value for that fact as if it were also true. Return JSON {\"title\": str, \"page\": str, "
        "\"old_span\": str, \"new_span\": str, \"question\": str} where old_span is an exact substring of the original page (10-200 chars), "
        "new_span is an exact substring of your new page stating the conflicting value, and question asks for that fact.",
}


# ─── generation ───────────────────────────────────────────────────────

LOOKALIKE_MIN_SPAN = 10  # lookalike/superseded spans may be as short as 10 characters
IDENT = re.compile(r"\b[A-Za-z_][A-Za-z0-9]*(?:[._/-][A-Za-z0-9]+)+\b|\b[a-z]+[A-Z][A-Za-z0-9]+\b|\b[A-Za-z]+[0-9][A-Za-z0-9]*\b")


class Generator:
    def __init__(self):
        self.pages = json.loads((WORK / "pages.json").read_text())
        self.by_id = {p["id"]: p for p in self.pages}
        self.state_path = WORK / "generated.json"
        state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {"accepted": [], "rejected": Counter(), "used": []}
        self.accepted, self.rejected, self.used = state["accepted"], Counter(state["rejected"]), set(state["used"])
        labels = WORK / "labels.json"
        self.label_rejects = {k for k, v in (json.loads(labels.read_text()) if labels.exists() else {}).items() if v.get("verdict") == "reject"}
        self.llm = LocalModel()
        self.all_norm = [norm(p["body"]) for p in self.pages]
        tokens = defaultdict(set)
        for p in self.pages:
            for token in set(IDENT.findall(p["body"])):
                if 6 <= len(token) <= 60:
                    tokens[token].add(p["id"])
        self.unique_tokens = defaultdict(list)
        for token, owners in tokens.items():
            if len(owners) == 1:
                self.unique_tokens[next(iter(owners))].append(token)

    def save(self):
        write_json(self.state_path, {"accepted": self.accepted, "rejected": dict(self.rejected), "used": sorted(self.used)})

    def count(self, slice_name):
        return sum(1 for q in self.accepted if q["slice"] == slice_name and q["id"] not in self.label_rejects)

    def candidates(self, slice_name):
        pool = [p for p in self.pages if p["eligible"]]
        pool.sort(key=lambda p: order_key(slice_name, p["id"]))
        return pool

    def reject(self, slice_name, reason):
        self.rejected[f"{slice_name}:{reason}"] += 1
        return None

    def span_ok(self, span, body, lo=20, hi=300):
        return isinstance(span, str) and lo <= len(span) <= hi and span in body

    def elsewhere(self, span, page_ids, min_len=20):
        """Does the span occur verbatim in a page outside page_ids? (ambiguity flag)"""
        key = norm(span)
        return len(key) >= min_len and any(key in body for p, body in zip(self.pages, self.all_norm) if p["id"] not in page_ids)

    def page_text(self, page):
        return f"TITLE: {page['title']}\n\n{page['body']}"

    def accept(self, item):
        item["id"] = f"q-{item['slice']}-{sha(json.dumps(item, sort_keys=True, ensure_ascii=False))[:12]}"
        self.accepted.append(item)
        self.used.update(item["pages_used"])

    # each attempt returns an item or None
    def attempt(self, slice_name, page):
        body, text = page["body"], self.page_text(page)
        if slice_name == "identifier_exact":
            tokens = sorted(self.unique_tokens.get(page["id"], []), key=lambda t: order_key("token", t))
            if not tokens:
                return self.reject(slice_name, "no-unique-identifier")
            token = tokens[0]
            out = self.llm(PROMPTS[slice_name], f"IDENTIFIER: {token}\n\nPAGE:\n{text}")
            if not out or not isinstance(out.get("question"), str) or token not in out["question"]:
                return self.reject(slice_name, "identifier-not-in-question")
            if not self.span_ok(out.get("span"), body):
                return self.reject(slice_name, "span-not-verbatim")
            return self.positive(slice_name, page, out, extra={"identifier": token})
        if slice_name in ("paraphrase", "cross_language_ukrainian"):
            out = self.llm(PROMPTS[slice_name], f"PAGE:\n{text}")
            if not out or not isinstance(out.get("question"), str) or not self.span_ok(out.get("span"), body):
                return self.reject(slice_name, "span-not-verbatim")
            if slice_name == "cross_language_ukrainian":
                if cyrillic_share(out["question"]) < 0.6:
                    return self.reject(slice_name, "not-ukrainian")
            else:
                q = content_words(out["question"])
                overlap = len(q & content_words(body)) / max(1, len(q))
                if overlap > 0.4:
                    return self.reject(slice_name, "lexical-overlap-too-high")
            return self.positive(slice_name, page, out)
        if slice_name == "multi_page":
            partners = [self.by_id[l] for l in page["links"] if l in self.by_id and self.by_id[l]["eligible"] and l not in self.used]
            if not partners and page["tags"]:
                partners = sorted((p for p in self.pages if p["eligible"] and p["id"] != page["id"] and p["id"] not in self.used
                                   and set(p["tags"]) & set(page["tags"])), key=lambda p: order_key("partner", page["id"], p["id"]))[:1]
            if not partners:
                return self.reject(slice_name, "no-partner")
            other = partners[0]
            out = self.llm(PROMPTS[slice_name], f"PAGE A:\n{text}\n\nPAGE B:\n{self.page_text(other)}")
            if not out or out.get("skip"):
                return self.reject(slice_name, "model-skip")
            if not (self.span_ok(out.get("span_a"), body) and self.span_ok(out.get("span_b"), other["body"])):
                return self.reject(slice_name, "span-not-verbatim")
            if out["span_b"] in body or out["span_a"] in other["body"]:
                return self.reject(slice_name, "single-page-answerable")
            ids = [page["id"], other["id"]]
            return {"slice": slice_name, "query": out["question"], "language": "en", "project": "main",
                    "expected": "answer", "answer": out.get("answer", ""),
                    "gold": [{"page": page["id"], "span": out["span_a"]}, {"page": other["id"], "span": out["span_b"]}],
                    "pages_used": ids, "edits": [],
                    "needs_label": self.elsewhere(out["span_a"], ids) or self.elsewhere(out["span_b"], ids)}
        if slice_name in ("superseded_decision", "cross_project_lookalike"):
            out = self.llm(PROMPTS[slice_name], f"PAGE:\n{text}")
            old, new = (out or {}).get("old_span"), (out or {}).get("new_span")
            if not (isinstance(old, str) and isinstance(new, str) and 10 <= len(old) <= 200 and body.count(old) == 1 and new.strip() and norm(new) != norm(old)):
                return self.reject(slice_name, "invalid-edit")
            if not isinstance(out.get("question"), str) or norm(old) in norm(out["question"]) or norm(new) in norm(out["question"]):
                return self.reject(slice_name, "question-quotes-span")
            changed = body.replace(old, new, 1)
            if not edit_ok(slice_name, old, new, changed):
                return self.reject(slice_name, "old-text-survives")
            if slice_name == "superseded_decision" and any(norm(old) in b for p, b in zip(self.pages, self.all_norm) if p["id"] != page["id"]):
                return self.reject(slice_name, "old-text-elsewhere")
            if slice_name == "superseded_decision":
                edits = [{"kind": "supersede", "project": "main", "page": page["id"], "body": changed, "actor": "owner"}]
                gold = [{"page": page["id"], "span": new, "revision": "current"}]
                extra = {"superseded_span": old}
            else:
                edits = [{"kind": "lookalike", "project": "lookalike", "page": page["id"], "body": changed, "actor": "owner"}]
                gold = [{"page": page["id"], "span": old}]
                extra = {"lookalike_span": new}
            # A lookalike gold span that also occurs on another main page may have more answering pages (D13).
            ambiguous = slice_name == "cross_project_lookalike" and self.elsewhere(old, [page["id"]], LOOKALIKE_MIN_SPAN)
            return {"slice": slice_name, "query": out["question"], "language": "en", "project": "main", "expected": "answer",
                    "answer": out.get("answer", ""), "gold": gold, "pages_used": [page["id"]], "edits": edits,
                    "needs_label": ambiguous, **extra}
        if slice_name == "child_written_fact":
            out = self.llm(PROMPTS[slice_name], f"PAGE:\n{text}")
            note, decision = (out or {}).get("note"), (out or {}).get("decision")
            if not (isinstance(note, str) and isinstance(decision, str) and decision.startswith("Decision:") and decision in note and len(decision) >= 25):
                return self.reject(slice_name, "invalid-note")
            if any(norm(decision) in body_n for body_n in self.all_norm):
                return self.reject(slice_name, "decision-not-new")
            if not isinstance(out.get("question"), str) or norm(decision) in norm(out["question"]):
                return self.reject(slice_name, "question-quotes-span")
            child_id = f"child-note-{sha(page['id'] + decision)[:10]}"
            return {"slice": slice_name, "query": out["question"], "language": "en", "project": "main", "expected": "answer",
                    "answer": out.get("answer", ""), "gold": [{"page": child_id, "span": decision}],
                    "pages_used": [page["id"]], "needs_label": False,
                    "edits": [{"kind": "child", "project": "main", "page": child_id, "title": str(out.get("title") or "Child note")[:200],
                               "body": note, "actor": "child", "derived_from": page["id"]}]}
        if slice_name == "missing_control":
            out = self.llm(PROMPTS[slice_name], f"PAGE:\n{text}")
            if not out or not isinstance(out.get("question"), str) or len(out["question"]) < 15:
                return self.reject(slice_name, "invalid-question")
            return {"slice": slice_name, "query": out["question"], "language": "en", "project": "main",
                    "expected": "abstain-missing", "gold": [], "about": page["id"], "why_absent": out.get("why_absent", ""),
                    "pages_used": [page["id"]], "edits": [], "needs_label": True}
        if slice_name == "conflict_control":
            out = self.llm(PROMPTS[slice_name], f"PAGE:\n{text}")
            new_page, old, new = (out or {}).get("page"), (out or {}).get("old_span"), (out or {}).get("new_span")
            if not (isinstance(new_page, str) and isinstance(old, str) and isinstance(new, str) and body.count(old) == 1
                    and new in new_page and norm(new) != norm(old) and isinstance(out.get("question"), str)):
                return self.reject(slice_name, "invalid-conflict")
            conflict_id = f"conflict-{sha(page['id'] + new)[:10]}"
            return {"slice": slice_name, "query": out["question"], "language": "en", "project": "main",
                    "expected": "abstain-conflict", "gold": [{"page": page["id"], "span": old}, {"page": conflict_id, "span": new}],
                    "pages_used": [page["id"]], "needs_label": True,
                    "edits": [{"kind": "conflict", "project": "main", "page": conflict_id, "title": str(out.get("title") or "Note")[:200],
                               "body": new_page, "actor": "owner"}]}
        raise ValueError("unknown slice")

    def positive(self, slice_name, page, out, extra=None):
        return {"slice": slice_name, "query": out["question"], "language": "uk" if slice_name == "cross_language_ukrainian" else "en",
                "project": "main", "expected": "answer", "answer": out.get("answer", ""),
                "gold": [{"page": page["id"], "span": out["span"]}], "pages_used": [page["id"]], "edits": [],
                "needs_label": self.elsewhere(out["span"], [page["id"]]), **(extra or {})}

    def run(self, only=None, max_attempts=MAX_ATTEMPTS_PER_SLICE):
        for slice_name, quota in QUOTAS.items():
            if only and slice_name not in only:
                continue
            tried = sum(v for k, v in self.rejected.items() if k.startswith(slice_name + ":")) + \
                sum(1 for q in self.accepted if q["slice"] == slice_name)
            for page in self.candidates(slice_name):
                if self.count(slice_name) >= quota:
                    break
                if tried >= max_attempts * quota:
                    print(f"{slice_name}: attempt budget exhausted at {self.count(slice_name)}/{quota}")
                    break
                if page["id"] in self.used:
                    continue
                tried += 1
                item = self.attempt(slice_name, page)
                if item:
                    self.accept(item)
                if tried % 10 == 0:
                    self.save()
                    print(f"{slice_name}: {self.count(slice_name)}/{quota} accepted after {tried} attempts, llm calls {self.llm.calls}", flush=True)
            self.save()
            print(f"{slice_name}: done {self.count(slice_name)}/{quota}", flush=True)


def cmd_generate(args) -> None:
    Generator().run(args.slice, args.max_attempts)


# ─── labeling page (local file only) ──────────────────────────────────

def cmd_label_page(_args) -> None:
    gen = Generator()
    sug_path = WORK / "suggestions.json"
    suggestions = json.loads(sug_path.read_text()) if sug_path.exists() else {}
    items = []
    for q in gen.accepted:
        if not q["needs_label"]:
            continue
        shown, cands = label_context(gen, q)
        items.append({"id": q["id"], "slice": q["slice"], "query": q["query"], "expected": q["expected"],
                      "answer": q.get("answer", ""), "why_absent": q.get("why_absent", ""), "gold": q["gold"],
                      "pages": [{"id": p["id"], "title": p["title"], "body": p["body"]} for p in shown],
                      "candidates": [{"id": p["id"], "title": p["title"], "body": p["body"]} for p in cands],
                      "suggestion": suggestions.get(q["id"])})
    items.sort(key=lambda i: (bool((i["suggestion"] or {}).get("verified")), (i["suggestion"] or {}).get("verdict") != "reject", i["id"]))
    template = (ROOT / "src" / "eval" / "labeling.html").read_text()
    page = template.replace("/*ITEMS*/[]", json.dumps(items, ensure_ascii=False).replace("</", "<\\/"))
    out = WORK / "labeling.html"
    out.write_text(page)
    print(f"label items={len(items)} by slice={dict(Counter(i['slice'] for i in items))}")
    print(f"open locally: file://{out}")


# ─── assisted labeling: local skeptical judge (DECISIONS.md D6) ───────

JUDGE = {
    "missing_control": "You check a NEGATIVE evaluation question that should have NO answer in the wiki. Read every page given "
        "(the source page and the most related other wiki pages). Decide whether some page directly states the specific answer. "
        "A page that only covers the same topic, or gives related but different details, does NOT answer it. "
        "If a page answers it, you MUST copy the answering sentence exactly, character for character, as quote. "
        "Return JSON {\"answered\": bool, \"page\": page id or null, \"quote\": exact text copied from that page or null, "
        "\"natural\": bool (would a developer plausibly ask this?), \"reason\": str (one sentence)}.",
    "conflict_control": "You audit a CONFLICT evaluation question: two pages are meant to state incompatible values for the fact the question asks. "
        "Be skeptical. Accept only if both spans answer the question, the values genuinely cannot both be true, and the question is natural. "
        "Reject if the values are compatible, differ only in wording or units, or the question asks about something else. "
        "Return JSON {\"verdict\": \"accept\"|\"reject\", \"confidence\": number 0-1, \"reason\": str (one sentence)}.",
    "positive": "You audit a retrieval evaluation question with GOLD page(s) and a reference answer. Be skeptical. "
        "Accept only if the gold page(s) really answer the question and the question is natural and unambiguous. "
        "Then list which CANDIDATE pages ALSO fully answer the question on their own (they would be equally correct retrieval hits). "
        "Return JSON {\"verdict\": \"accept\"|\"reject\", \"confidence\": number 0-1, \"also_answering\": [candidate page ids], \"reason\": str (one sentence)}.",
}


def related_pages(gen, text: str, exclude: set, k: int = 5) -> list[dict]:
    """Top-k pages by IDF-weighted content-word overlap (deterministic, no model)."""
    if not hasattr(gen, "_words"):
        gen._words = [content_words(p["title"] + " " + p["body"]) for p in gen.pages]
        df = Counter(w for ws in gen._words for w in ws)
        gen._idf = {w: 1.0 / (1 + n) for w, n in df.items()}
    q = content_words(text)
    scored = [(sum(gen._idf.get(w, 0) for w in q & ws), order_key("rel", p["id"]), p)
              for p, ws in zip(gen.pages, gen._words) if p["id"] not in exclude]
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [p for score, _, p in scored[:k] if score > 0]


def clip(body: str, text: str, limit: int = 6000) -> str:
    """Whole body when short; otherwise the best-matching paragraphs, in order."""
    if len(body) <= limit:
        return body
    q = content_words(text)
    paras = [x for x in re.split(r"\n\s*\n", body) if x.strip()]
    ranked = sorted(range(len(paras)), key=lambda i: (-len(q & content_words(paras[i])), i))
    keep, size = set(), 0
    for i in ranked:
        if size + len(paras[i]) > limit:
            continue
        keep.add(i); size += len(paras[i])
    return "\n\n[...]\n\n".join(paras[i][:limit] for i in sorted(keep)) or body[:limit]


def label_context(gen, q) -> tuple[list[dict], list[dict]]:
    """(shown pages incl. synthetic edits, related/candidate pages) for one item."""
    shown = [gen.by_id[p] for p in q["pages_used"] if p in gen.by_id]
    shown += [{"id": e["page"], "title": e.get("title", e["page"]), "body": e["body"]} for e in q["edits"]]
    ids = {p["id"] for p in shown}
    cands = []
    for g in q["gold"]:
        key = norm(g["span"] or "")
        if len(key) >= LOOKALIKE_MIN_SPAN:
            cands += [p for p, b in zip(gen.pages, gen.all_norm) if key in b and p["id"] not in ids][:5]
    probe = q["query"] + " " + q.get("answer", "") + " " + " ".join(g["span"] or "" for g in q["gold"])
    for p in related_pages(gen, probe, ids | {c["id"] for c in cands}, k=5 if q["slice"] in CONTROLS else 3):
        cands.append(p)
    seen, out = set(), []
    for p in cands:
        if p["id"] not in seen:
            seen.add(p["id"]); out.append(p)
    return shown, out


def missing_verdict(r, pages: dict) -> dict:
    """Missing-control suggestion. A claimed answer counts only with a verbatim quote from a shown page."""
    r = r if isinstance(r, dict) else {}
    reason = str(r.get("reason") or "")[:500]
    base = {"extra_gold": [], "confidence": None, "reason": reason, "answering_page": None, "quote": None}
    if r.get("answered") is True:
        page, quote = r.get("page"), r.get("quote")
        ok = isinstance(quote, str) and len(norm(quote)) >= 15 and page in pages and norm(quote) in norm(pages[page]["body"])
        if ok:
            return {**base, "verdict": "reject", "verified": True, "answering_page": page, "quote": quote}
        return {**base, "verdict": None, "verified": False, "reason": "judge claims an answer exists but its quote was not found verbatim: " + reason}
    if r.get("answered") is False:
        if r.get("natural") is False:
            return {**base, "verdict": "reject", "verified": False, "reason": "judge finds the question unnatural: " + reason}
        return {**base, "verdict": "accept", "verified": True}
    return {**base, "verdict": None, "verified": False, "reason": "no usable judge output"}


def judge_request(gen, q) -> tuple[str, str, str, list, list]:
    """(kind, system prompt, user prompt, shown pages, candidate pages) for one item; same for every judge."""
    shown, cands = label_context(gen, q)
    probe = q["query"] + " " + q.get("answer", "")
    block = lambda tag, p: f"[{tag} id={p['id']}] TITLE: {p['title']}\n{clip(p['body'], probe)}"  # noqa: E731
    if q["slice"] == "missing_control":
        pages = "\n\n".join([block("SOURCE PAGE", p) for p in shown] + [block("OTHER PAGE", p) for p in cands])
        return "missing_control", JUDGE["missing_control"], f"QUESTION: {q['query']}\n\n{pages}", shown, cands
    if q["slice"] == "conflict_control":
        spans = "\n".join(f"- page {g['page']}: {g['span']}" for g in q["gold"])
        pages = "\n\n".join(block("PAGE", p) for p in shown)
        return "conflict_control", JUDGE["conflict_control"], f"QUESTION: {q['query']}\n\nCONFLICTING SPANS:\n{spans}\n\n{pages}", shown, cands
    gold = "\n\n".join(block("GOLD PAGE", p) for p in shown)
    cand = "\n\n".join(block("CANDIDATE", p) for p in cands)
    return "positive", JUDGE["positive"], f"QUESTION: {q['query']}\nREFERENCE ANSWER: {q.get('answer', '')}\n\n{gold}\n\n{cand}", shown, cands


def interpret(kind: str, r, shown: list, cands: list) -> dict:
    """Turn raw judge JSON into a suggestion; evidence checks are done here, by code."""
    if kind == "missing_control":
        return missing_verdict(r, {p["id"]: p for p in shown + cands})
    r = r if isinstance(r, dict) else {}
    verdict = r.get("verdict") if r.get("verdict") in ("accept", "reject") else None
    cand_ids = {p["id"] for p in cands}
    extra = [x for x in (r.get("also_answering") or []) if isinstance(x, str) and x in cand_ids] if kind == "positive" else []
    if verdict == "accept" and extra:
        verdict = "accept-with-gold"
    return {"verdict": verdict, "extra_gold": extra, "confidence": None, "verified": verdict is not None,
            "reason": str(r.get("reason") or "")[:500], "answering_page": None, "quote": None}


def summarize(out: dict) -> None:
    c = Counter(v["verdict"] for v in out.values())
    print(f"suggestions={len(out)} verdicts={dict(c)} unverified={sum(1 for v in out.values() if not v['verified'])}")


def cmd_suggest(_args) -> None:
    gen = Generator()
    out = {}
    items = [q for q in gen.accepted if q["needs_label"]]
    for n, q in enumerate(items, 1):
        kind, system, user, shown, cands = judge_request(gen, q)
        out[q["id"]] = {**interpret(kind, gen.llm(system, user), shown, cands), "judge": f"local:{MODEL}"}
        if n % 10 == 0:
            print(f"judged {n}/{len(items)}, llm calls {gen.llm.calls}", flush=True)
    write_json(WORK / "suggestions-local.json", out)
    write_json(WORK / "suggestions.json", out)
    summarize(out)


# Codex judge (DECISIONS.md D7): owner-approved exception to D5. Text goes to the Codex
# provider only through this function; nothing is printed. No user config, MCP servers,
# rules or repository access: empty working directory, read-only sandbox, ephemeral session.
CODEX_MODEL = "gpt-6.1-sol"
_NULLSTR = {"type": ["string", "null"]}
CODEX_SCHEMAS = {
    "missing_control": {"type": "object", "additionalProperties": False,
                        "required": ["answered", "page", "quote", "natural", "reason"],
                        "properties": {"answered": {"type": "boolean"}, "page": _NULLSTR, "quote": _NULLSTR,
                                       "natural": {"type": "boolean"}, "reason": {"type": "string"}}},
    "conflict_control": {"type": "object", "additionalProperties": False, "required": ["verdict", "reason"],
                         "properties": {"verdict": {"type": "string", "enum": ["accept", "reject"]}, "reason": {"type": "string"}}},
    "positive": {"type": "object", "additionalProperties": False, "required": ["verdict", "also_answering", "reason"],
                 "properties": {"verdict": {"type": "string", "enum": ["accept", "reject"]},
                                "also_answering": {"type": "array", "items": {"type": "string"}}, "reason": {"type": "string"}}},
}


def codex_call(kind: str, system: str, user: str, run_dir: Path) -> dict | None:
    import subprocess
    import tempfile
    prompt = (system + "\nIgnore the 'confidence' field if mentioned. Do not run commands or use tools: judge only from the text below.\n\n" + user)
    key = sha(CODEX_MODEL + "\x00" + kind + "\x00" + prompt)
    cache_path = WORK / "codex-cache.jsonl"
    for row in read_jsonl(cache_path):
        if row["key"] == key:
            return row["response"]
    with tempfile.TemporaryDirectory(dir=run_dir) as tmp:
        tmp = Path(tmp)
        (tmp / "empty").mkdir()
        (tmp / "schema.json").write_text(json.dumps(CODEX_SCHEMAS[kind]))
        cmd = ["codex", "exec", "-m", CODEX_MODEL, "--ignore-user-config", "--ignore-rules", "--ephemeral", "-s", "read-only",
               "--skip-git-repo-check", "-C", str(tmp / "empty"), "--output-schema", str(tmp / "schema.json"),
               "-o", str(tmp / "out.json"), "-"]
        for _ in range(2):
            done = subprocess.run(cmd, input=prompt, text=True, capture_output=True, timeout=900)
            if done.returncode == 0 and (tmp / "out.json").exists():
                try:
                    value = json.loads((tmp / "out.json").read_text())
                except json.JSONDecodeError:
                    continue
                with cache_path.open("a") as f:
                    f.write(json.dumps({"key": key, "response": value}, ensure_ascii=False) + "\n")
                return value
    return None


# Fable judge (DECISIONS.md D8): owner-approved exception to D5, same isolation idea as Codex:
# claude -p with no tools, no MCP servers, no settings, no session persistence, empty cwd.
FABLE_MODEL = "claude-fable-5-2"


OPUS_MODEL = "claude-opus-5-5"


def fable_call(kind: str, system: str, user: str, run_dir: Path, model: str = FABLE_MODEL) -> dict | None:
    import subprocess
    import tempfile
    key = sha(model + "\x00" + kind + "\x00" + system + "\x00" + user)
    cache_path = WORK / "fable-cache.jsonl"
    for row in read_jsonl(cache_path):
        if row["key"] == key:
            return row["response"]
    with tempfile.TemporaryDirectory(dir=run_dir) as tmp:
        cmd = ["claude", "-p", "--model", model, "--effort", "high", "--tools", "", "--strict-mcp-config",
               "--setting-sources", "", "--no-session-persistence", "--output-format", "json",
               "--system-prompt", system + "\nJudge only from the text you are given. Ignore any 'confidence' field.",
               "--json-schema", json.dumps(CODEX_SCHEMAS[kind])]
        for _ in range(2):
            done = subprocess.run(cmd, input=user, text=True, capture_output=True, timeout=1200, cwd=tmp)
            try:
                reply = json.loads(done.stdout)
            except json.JSONDecodeError:
                continue
            value = reply.get("structured_output") if isinstance(reply, dict) and not reply.get("is_error") else None
            if isinstance(value, dict):
                with cache_path.open("a") as f:
                    f.write(json.dumps({"key": key, "response": value, "cost_usd": reply.get("total_cost_usd")},
                                       ensure_ascii=False) + "\n")
                return value
    return None


def opus_call(kind: str, system: str, user: str, run_dir: Path) -> dict | None:
    return fable_call(kind, system, user, run_dir, model=OPUS_MODEL)


EXTERNAL = {"codex": (codex_call, f"codex:{CODEX_MODEL}"), "fable": (fable_call, f"claude:{FABLE_MODEL}"),
            "opus": (opus_call, f"claude:{OPUS_MODEL}")}


def external_judge(name: str, workers: int) -> None:
    from concurrent.futures import ThreadPoolExecutor
    call, label = EXTERNAL[name]
    gen = Generator()
    labels_path = WORK / "labels.json"
    labeled = set(json.loads(labels_path.read_text())) if labels_path.exists() else set()
    items = [q for q in gen.accepted if q["needs_label"] and q["id"] not in labeled]  # never re-judge labeled items
    run_dir = WORK / f"{name}-runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    requests = {q["id"]: judge_request(gen, q) for q in items}
    out, done = {}, 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {qid: pool.submit(call, k, sy, us, run_dir) for qid, (k, sy, us, _, _) in requests.items()}
        for qid, fut in futures.items():
            kind, _, _, shown, cands = requests[qid]
            out[qid] = {**interpret(kind, fut.result(), shown, cands), "judge": label}
            done += 1
            if done % 10 == 0:
                print(f"judged {done}/{len(items)}", flush=True)
    def merged(path):
        return {**(json.loads(path.read_text()) if path.exists() else {}), **out}
    write_json(WORK / f"suggestions-{name}.json", merged(WORK / f"suggestions-{name}.json"))
    write_json(WORK / "suggestions.json", merged(WORK / "suggestions.json"))
    summarize(out)
    for other in ("local", "codex", "fable", "opus"):
        path = WORK / f"suggestions-{other}.json"
        if other == name or not path.exists():
            continue
        prev = json.loads(path.read_text())
        both = [qid for qid in out if qid in prev and out[qid]["verdict"] and prev[qid]["verdict"]]
        agree = sum(1 for qid in both if out[qid]["verdict"] == prev[qid]["verdict"])
        print(f"agreement with {other} judge: {agree}/{len(both)} items where both gave a verdict")
    if name in ("fable", "opus"):
        cost = sum(r.get("cost_usd") or 0 for r in read_jsonl(WORK / "fable-cache.jsonl"))
        print(f"claude judges cumulative cost_usd={cost:.2f}")


def cmd_codex_judge(args) -> None:
    external_judge("codex", args.workers)


def cmd_fable_judge(args) -> None:
    external_judge("fable", args.workers)


def cmd_opus_judge(args) -> None:
    external_judge("opus", args.workers)


# Fable second pass: the judge first names what it is missing; code fetches it from the
# local corpus; then the judge decides with that extra evidence. Same isolation as fable_call.
NEED_PROMPT = ("You are about to judge an evaluation item (instructions below), but first say what extra information "
    "you need to decide it confidently. You may ask for: a full page by id (kind=page), a keyword search over the whole "
    "wiki (kind=search, returns the 5 best matching pages), or all pages containing an exact phrase (kind=phrase). "
    "Ask for at most 5 things. If you already have enough, return an empty list.\n\nJUDGE INSTRUCTIONS:\n")
NEED_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["requests", "why"],
               "properties": {"requests": {"type": "array", "maxItems": 5, "items": {
                   "type": "object", "additionalProperties": False, "required": ["kind", "value"],
                   "properties": {"kind": {"type": "string", "enum": ["page", "search", "phrase"]}, "value": {"type": "string"}}}},
                   "why": {"type": "string"}}}


def claude_json(system: str, user: str, schema: dict, tag: str, run_dir: Path) -> dict | None:
    import subprocess
    import tempfile
    key = sha(FABLE_MODEL + "\x00" + tag + "\x00" + system + "\x00" + user)
    cache_path = WORK / "fable-cache.jsonl"
    for row in read_jsonl(cache_path):
        if row["key"] == key:
            return row["response"]
    with tempfile.TemporaryDirectory(dir=run_dir) as tmp:
        cmd = ["claude", "-p", "--model", FABLE_MODEL, "--effort", "high", "--tools", "", "--strict-mcp-config",
               "--setting-sources", "", "--no-session-persistence", "--output-format", "json",
               "--system-prompt", system, "--json-schema", json.dumps(schema)]
        for _ in range(2):
            done = subprocess.run(cmd, input=user, text=True, capture_output=True, timeout=1800, cwd=tmp)
            try:
                reply = json.loads(done.stdout)
            except json.JSONDecodeError:
                continue
            value = reply.get("structured_output") if isinstance(reply, dict) and not reply.get("is_error") else None
            if isinstance(value, dict):
                with cache_path.open("a") as f:
                    f.write(json.dumps({"key": key, "response": value, "cost_usd": reply.get("total_cost_usd")},
                                       ensure_ascii=False) + "\n")
                return value
    return None


def fulfil(gen, requests: list, synthetic: dict, budget: int = 60000) -> tuple[str, list, Counter]:
    """Answer the judge's information requests from the local corpus. Returns (text, pages served, counts)."""
    pool = {p["id"]: p for p in gen.pages} | synthetic
    parts, served, counts, used = [], [], Counter(), 0
    for r in requests[:5]:
        kind, value = r.get("kind"), str(r.get("value") or "")
        if kind == "page":
            hits = [pool[value]] if value in pool else []
        elif kind == "search":
            hits = related_pages(gen, value, exclude=set(), k=5)
        elif kind == "phrase":
            key = norm(value)
            hits = [p for p, body in zip(gen.pages, gen.all_norm) if len(key) >= 4 and key in body][:5]
            hits += [p for p in synthetic.values() if len(key) >= 4 and key in norm(p["body"])][:2]
        else:
            continue
        counts[f"{kind}:{'hit' if hits else 'empty'}"] += 1
        parts.append(f"## REQUEST {kind}: {value}\n" + ("(nothing found)" if not hits else ""))
        for p in hits:
            text = clip(p["body"], value, limit=12000)
            if used + len(text) > budget:
                parts.append("(budget exhausted)")
                break
            used += len(text)
            served.append(p)
            parts.append(f"[EXTRA PAGE id={p['id']}] TITLE: {p['title']}\n{text}")
    return "\n\n".join(parts), served, counts


def cmd_fable_deep(args) -> None:
    from concurrent.futures import ThreadPoolExecutor
    gen = Generator()
    fable = json.loads((WORK / "suggestions-fable.json").read_text())
    codex_path = WORK / "suggestions-codex.json"
    codex = json.loads(codex_path.read_text()) if codex_path.exists() else {}
    acc = lambda v: (v or "").startswith("accept")  # noqa: E731
    doubtful = [q for q in gen.accepted if q["needs_label"] and q["id"] in fable and
                (not fable[q["id"]]["verified"] or (q["id"] in codex and acc(fable[q["id"]]["verdict"]) != acc(codex[q["id"]]["verdict"])))]
    run_dir = WORK / "fable-runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    all_counts = Counter()

    def one(q):
        kind, system, user, shown, cands = judge_request(gen, q)
        synthetic = {e["page"]: {"id": e["page"], "title": e.get("title", e["page"]), "body": e["body"]} for e in q["edits"]}
        need = claude_json(NEED_PROMPT + system, user, NEED_SCHEMA, "need", run_dir) or {"requests": []}
        extra_text, served, counts = fulfil(gen, need.get("requests") or [], synthetic)
        final_user = user + ("\n\nADDITIONAL INFORMATION YOU REQUESTED:\n" + extra_text if extra_text else "")
        r = claude_json(system + "\nJudge only from the text you are given.", final_user, CODEX_SCHEMAS[kind], "final", run_dir)
        seen = {p["id"] for p in shown + cands}
        return q["id"], interpret(kind, r, shown + [p for p in served if p["id"] not in seen], cands), counts, len(need.get("requests") or [])

    out, asked = {}, Counter()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for qid, sug, counts, n in pool.map(one, doubtful):
            out[qid] = {**sug, "judge": f"claude:{FABLE_MODEL}+requested-info"}
            all_counts.update(counts)
            asked[n] += 1
    write_json(WORK / "suggestions-fable-deep.json", out)
    merged = {**fable, **out}
    write_json(WORK / "suggestions.json", merged)
    changed = sum(1 for qid in out if acc(out[qid]["verdict"]) != acc(fable[qid]["verdict"]) or out[qid]["verdict"] is None)
    print(f"doubtful items={len(doubtful)} requests_per_item={dict(sorted(asked.items()))} served={dict(all_counts)}")
    summarize(out)
    print(f"verdict changed vs first fable pass: {changed}/{len(out)}")
    both = [qid for qid in out if qid in codex and out[qid]["verdict"] and codex[qid]["verdict"]]
    print(f"now agree with codex: {sum(1 for qid in both if acc(out[qid]['verdict']) == acc(codex[qid]['verdict']))}/{len(both)}")
    cost = sum(r.get("cost_usd") or 0 for r in read_jsonl(WORK / "fable-cache.jsonl"))
    print(f"fable cumulative cost_usd={cost:.2f}")


def cmd_delegate_labels(_args) -> None:
    """Owner delegates labeling to the current judge suggestions (DECISIONS.md D9). Never overwrites owner labels."""
    gen = Generator()
    sugg = json.loads((WORK / "suggestions.json").read_text())
    path = WORK / "labels.json"
    labels = json.loads(path.read_text()) if path.exists() else {}
    need = [q["id"] for q in gen.accepted if q["needs_label"]]
    added, undecided = 0, 0
    for qid in need:
        if labels.get(qid, {}).get("verdict"):
            continue
        s = sugg.get(qid) or {}
        if not s.get("verdict"):
            undecided += 1
            continue
        labels[qid] = {"verdict": s["verdict"], "extra_gold": s.get("extra_gold") or [], "source": "delegated",
                       "judge": s.get("judge", "unknown"), "verified": bool(s.get("verified"))}
        added += 1
    write_json(path, labels)
    print(f"labels={len(labels)}/{len(need)} added_delegated={added} undecided={undecided} "
          f"verdicts={dict(Counter(v['verdict'] for v in labels.values()))}")


# ─── freeze ───────────────────────────────────────────────────────────

def cmd_freeze(_args) -> None:
    gen = Generator()
    labels_path = WORK / "labels.json"
    labels = json.loads(labels_path.read_text()) if labels_path.exists() else {}
    unlabeled = [q["id"] for q in gen.accepted if q["needs_label"] and q["id"] not in labels]
    if unlabeled:
        raise SystemExit(f"freeze refused: {len(unlabeled)} items still need owner labels")
    final = []
    for q in gen.accepted:
        verdict = labels.get(q["id"], {})
        if verdict.get("verdict") == "reject":
            continue
        q = dict(q)
        if verdict.get("verdict") == "accept-with-gold" and verdict.get("extra_gold"):
            q["gold"] = q["gold"] + [{"page": p, "span": None, "label": "owner-added"} for p in verdict["extra_gold"]]
        q["label"] = verdict.get("verdict", "auto")
        final.append(q)
    counts = Counter(q["slice"] for q in final)
    short = {s: (counts[s], n) for s, n in QUOTAS.items() if counts[s] < n}
    if short:
        raise SystemExit(f"freeze refused: quotas unmet after labeling {short}; rerun generate to refill")
    prev_path = WORK / "frozen" / "split.json"
    prev = json.loads(prev_path.read_text()) if prev_path.exists() else {}
    split = {}
    for slice_name in QUOTAS:
        ids = sorted((q["id"] for q in final if q["slice"] == slice_name), key=lambda i: order_key("split", i))[:QUOTAS[slice_name]]
        cut = round(0.4 * len(ids))
        # Earlier assignments never move (no item crosses development/holdout); new items fill the gaps.
        for qid in ids:
            if qid in prev:
                split[qid] = prev[qid]
        for qid in ids:
            if qid not in split:
                dev = sum(1 for i in ids if split.get(i) == "development")
                split[qid] = "development" if dev < cut else "holdout"
    final = [q for q in final if q["id"] in split]
    _, invalid = settle_valid(gen.pages, final)  # checked on the exact frozen set, immediately before writing
    if invalid:
        raise SystemExit(f"freeze refused: {len(invalid)} items invalid against the final corpus; run revalidate and refill")
    edits = [e for q in final for e in q["edits"]]
    frozen = WORK / "frozen"
    write_json(frozen / "questions.json", final)
    write_json(frozen / "split.json", split)
    write_json(frozen / "pages.json", gen.pages)
    write_json(frozen / "edits.json", edits)
    files = {name: hashlib.sha256((frozen / name).read_bytes()).hexdigest() for name in ("questions.json", "split.json", "pages.json", "edits.json")}
    holdout = Counter(next(q["slice"] for q in final if q["id"] == i) for i, s in split.items() if s == "holdout")
    manifest = {
        "version": "2", "seed": SEED, "source": "pi-llm-wiki", "source_pages": len(gen.pages),
        "generator": {"endpoint": "local-llamacpp", "model": MODEL, "temperature": 0, "seed": 7, "thinking": False,
                      "prompts_sha256": {k: sha(v) for k, v in PROMPTS.items()}},
        "builder_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "counts": dict(counts), "holdout_counts": dict(holdout),
        "owner_labels": {"labeled": len(labels), "rejected": sum(1 for v in labels.values() if v.get("verdict") == "reject"),
                         "by_source": dict(Counter(v.get("source", "owner") for v in labels.values())),
                         "assist": "judge suggestions; see by_judge (DECISIONS.md D6, D7, D8)",
                         "by_judge": dict(Counter(v.get("judge", "owner") for v in labels.values())),
                         "judge_prompts_sha256": {k: sha(v) for k, v in JUDGE.items()}},
        "files_sha256": files, "data_location": ".cache/eval/v2/frozen (not in git; confidential)",
        "thresholds": THRESHOLDS,
    }
    write_json(MANIFEST, manifest)
    print(f"frozen questions={len(final)} holdout={sum(holdout.values())} manifest={MANIFEST.relative_to(ROOT)}")


def cmd_status(_args) -> None:
    gen = Generator()
    print("accepted", {s: f"{gen.count(s)}/{n}" for s, n in QUOTAS.items()})
    print("needs_label", sum(1 for q in gen.accepted if q["needs_label"]))
    print("rejections", dict(sorted(gen.rejected.items())))
    print("llm cache entries", len(gen.llm.cache))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("select")
    g = sub.add_parser("generate")
    g.add_argument("--slice", action="append", choices=list(QUOTAS))
    g.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS_PER_SLICE,
                   help="attempt budget as a multiple of quota (validators are unchanged)")
    sub.add_parser("suggest")
    cj = sub.add_parser("codex-judge")
    cj.add_argument("--workers", type=int, default=4)
    fj = sub.add_parser("fable-judge")
    fj.add_argument("--workers", type=int, default=4)
    oj = sub.add_parser("opus-judge")
    oj.add_argument("--workers", type=int, default=4)
    fd = sub.add_parser("fable-deep")
    fd.add_argument("--workers", type=int, default=4)
    sub.add_parser("delegate-labels")
    sub.add_parser("label-page")
    sub.add_parser("freeze")
    sub.add_parser("revalidate")
    sub.add_parser("flag-ambiguous")
    sub.add_parser("status")
    args = parser.parse_args()
    {"select": cmd_select, "generate": cmd_generate, "suggest": cmd_suggest, "codex-judge": cmd_codex_judge, "fable-judge": cmd_fable_judge, "fable-deep": cmd_fable_deep, "opus-judge": cmd_opus_judge, "delegate-labels": cmd_delegate_labels, "label-page": cmd_label_page,
     "freeze": cmd_freeze, "revalidate": cmd_revalidate, "flag-ambiguous": cmd_flag_ambiguous, "status": cmd_status}[args.command](args)


if __name__ == "__main__":
    main()
