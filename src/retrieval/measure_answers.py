#!/usr/bin/env python3
"""Approved-local-model extractive-answer measurement, not a semantic-correctness oracle."""
import concurrent.futures
import hashlib
import importlib.util
import json
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src/authority"))
from authority import connect_knowledge
spec = importlib.util.spec_from_file_location("wiki_rpc", ROOT / "src/mcp/authority_rpc.py")
rpc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rpc)
MODEL = "qwen3.8-35b-a3b-mtp-32k"


def measure(output):
    config = json.loads((Path.home() / ".pi/agent/models.json").read_text())["providers"]["local-llamacpp"]
    # This is the existing approved endpoint, not a caller-selected provider.
    if config["baseUrl"].rstrip("/") != "http://192.168.0.30:8080/v1":
        raise RuntimeError("approved local endpoint changed; refusing corpus transmission")
    endpoint = config["baseUrl"].rstrip("/")
    headers = {"Content-Type": "application/json"}
    key = config.get("apiKey")
    if isinstance(key, str) and key and not key.startswith(("!", "${")):
        headers["Authorization"] = "Bearer " + key
    with urllib.request.urlopen(urllib.request.Request(endpoint + "/models", headers=headers), timeout=15) as response:
        if MODEL not in {m["id"] for m in json.load(response)["data"]}:
            raise RuntimeError("pinned answer model is not served")
    frozen = ROOT / "research/eval-corpus/frozen/v1"
    questions = json.loads((frozen / "questions.json").read_text())
    documents = json.loads((frozen / "documents.json").read_text())
    by_id = {d["id"]: d for d in documents}
    # Bounded feasibility run: four SHA256-ordered questions from each slice.
    # This is not the full corpus and not an independently frozen holdout.
    grouped = {}
    for question in questions:
        slice_name = by_id[question["gold_pages"][0]]["slice_type"]
        grouped.setdefault(slice_name, []).append(question)
    questions = [q for group in grouped.values()
                 for q in sorted(group, key=lambda q: hashlib.sha256(q["id"].encode()).hexdigest())[:4]]
    inputs = []
    with tempfile.TemporaryDirectory(prefix="wiki-answer-eval-") as tmp:
        database = str(Path(tmp) / "answers.db")
        stores = {}
        for document in documents:
            project = document["project"]
            if project not in stores:
                stores[project] = connect_knowledge(database, project)
            stores[project].create_page(project, document["id"], document["title"], document["body"], "local-evaluator")
        for question in questions:
            project = by_id[question["gold_pages"][0]]["project"]
            evidence = rpc.lexical_recall(stores[project], project, {"query": question["query"], "maxBytes": 24000})
            inputs.append((question, evidence))

    def one(item):
        question, evidence = item
        messages = [
            {"role": "system", "content": "Answer from supplied project evidence only. Return JSON with abstain boolean, quote string, page string, revision string, hash string. If evidence does not answer the question, or conflicts, abstain true and empty quote. Otherwise quote one exact supporting span from the evidence, at most 400 characters. Never invent facts or citations."},
            {"role": "user", "content": json.dumps({"question": question["query"], "evidence": evidence}, ensure_ascii=False)},
        ]
        # Conservative 1-byte/token upper bound fits the 32k input budget minus 4096 reserve.
        if len(json.dumps(messages, ensure_ascii=False).encode()) > 32000 - 4096:
            raise RuntimeError("pinned input budget exceeded")
        payload = {"model": MODEL, "messages": messages, "max_tokens": 4096, "temperature": 0,
                   "chat_template_kwargs": {"enable_thinking": False}, "response_format": {"type": "json_object"}}
        record = {"id_sha256": hashlib.sha256(question["id"].encode()).hexdigest(),
                  "positive": question["is_positive"], "slice": by_id[question["gold_pages"][0]]["slice_type"]}
        try:
            request = urllib.request.Request(endpoint + "/chat/completions", data=json.dumps(payload).encode(), headers=headers)
            with urllib.request.urlopen(request, timeout=90) as response:
                answer = json.loads(json.load(response)["choices"][0]["message"]["content"])
            valid = isinstance(answer, dict) and type(answer.get("abstain")) is bool
            record["valid_json_contract"] = valid
            record["abstain"] = answer.get("abstain") if valid else None
            cited = next((p for p in evidence["evidence"]["passages"]
                          if p["page"] == answer.get("page") and p["revision"] == answer.get("revision")
                          and p["hash"] == answer.get("hash")), None) if valid else None
            quote = answer.get("quote", "") if isinstance(answer, dict) else ""
            record["exact_citation_and_quote"] = bool(cited and isinstance(quote, str) and quote and quote in cited["text"])
            record["gold_cited_extract"] = bool(record["exact_citation_and_quote"] and cited["page"] in question["gold_pages"])
        except Exception as error:
            record["error_type"] = type(error).__name__  # Never persist private prompt/answer text.
        return record

    records = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(one, item) for item in inputs]
        for future in concurrent.futures.as_completed(futures):
            records.append(future.result())
            output.write_text(json.dumps({"status": "RUNNING", "completed": len(records), "total": len(inputs)}, indent=2))
    positives = [r for r in records if r["positive"]]
    negatives = [r for r in records if not r["positive"]]
    valid_answers = [r for r in records if r.get("abstain") is False]
    report = {
        "status": "MEASURED_NOT_SEMANTIC_G2_CERTIFICATION", "provider": "local-llamacpp", "model": MODEL,
        "thinking_requested": "off", "input_budget": 32000, "output_reserve": 4096,
        "counting": "conservative UTF-8 bytes upper bound for tiktoken_cl100k; no tokenizer substitution",
        "sample": "four SHA256(id)-ordered questions per slice; bounded feasibility run",
        "corpus_sha256": {name: hashlib.sha256((frozen / name).read_bytes()).hexdigest()
                          for name in ("questions.json", "documents.json")},
        "total": len(records), "errors": sum("error_type" in r for r in records),
        "valid_json_contract_rate": sum(r.get("valid_json_contract", False) for r in records) / len(records),
        "positive_gold_cited_extract_rate": sum(r.get("gold_cited_extract", False) and r.get("abstain") is False for r in positives) / len(positives),
        "negative_nonabstention_rate": sum(r.get("abstain") is False for r in negatives) / len(negatives),
        "exact_citation_and_quote_rate_among_nonabstentions": sum(r.get("exact_citation_and_quote", False) for r in valid_answers) / len(valid_answers) if valid_answers else None,
        "records": sorted(records, key=lambda r: r["id_sha256"]),
        "limitations": ["Exact quote/gold provenance is measured, not semantic answer correctness.",
                        "Negative nonabstention is measured, not calibrated confidence.",
                        "Frozen v1 has no independently frozen question-level holdout assignment.",
                        "Thinking-off is requested via the endpoint template option; tokenizer/serving implementation is not independently audited."],
    }
    output.write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    measure(Path(sys.argv[1]))
