"""Verification receipts: run identity, schema validation and gate status.

A receipt records one tier run: which code and inputs ran (identity), the
commands and exits, and per-test outcomes. Gate status is computed only from
receipts whose identity equals the current checkout's. Prose is never evidence.

Stdlib only, so the checker runs without the test environment.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import stat
import subprocess
import sys
import tempfile
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECEIPT_SCHEMA = "llm-wiki/receipt/v1"
GATES_SCHEMA = "llm-wiki/gates/v1"
RECEIPT_DIR = ROOT / ".verification" / "receipts"
GATES_FILE = ROOT / "specs" / "wiki-system" / "gates.json"

# Files whose bytes define what a run tested besides the commit itself.
IDENTITY_INPUTS = (
    "pyproject.toml",
    "uv.lock",
    "package.json",
    "package-lock.json",
    "research/eval-corpus/frozen/v1/manifest.json",
    "specs/wiki-system/gates.json",
)
# Generated evidence never makes the tree dirty.
DIRTY_EXEMPT = (".verification/",)
TIERS = ("a", "b", "c")
OUTCOMES = ("passed", "failed", "error", "skipped")
STATUSES = ("PASS", "FAIL", "MISSING", "STALE", "EXPLORATORY")


class ReceiptError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_json(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True, timeout=30).stdout


def dirty_paths(root: Path) -> list[str]:
    raw = _git(root, "-c", "core.filemode=true", "status", "--porcelain=v1", "-z", "--untracked-files=all")
    paths = []
    entries = raw.split(b"\0")
    i = 0
    while i < len(entries):
        entry = os.fsdecode(entries[i])
        i += 1
        if not entry:
            continue
        status, path = entry[:2], entry[3:]
        if "R" in status or "C" in status:
            original = os.fsdecode(entries[i])
            i += 1
            if "R" in status and not original.startswith(DIRTY_EXEMPT):
                paths.append(original)
        if not path.startswith(DIRTY_EXEMPT):
            paths.append(path)
    return sorted(set(paths))


def node_version() -> str:
    try:
        return subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=10).stdout.strip()
    except OSError:
        return "missing"


def _reject_source_link(name: str) -> ReceiptError:
    return ReceiptError(f"cannot fingerprint checkout symlink {name}; replace it with a regular in-checkout file or directory")


def _check_source_links(root: Path) -> None:
    # A committed link can be clean while the code it points to changes.
    def raise_walk_error(error):
        raise error

    for name in ("src", "scripts", "tsconfig.json"):
        path = root / name
        if path.is_symlink():
            raise _reject_source_link(name)
        if name == "tsconfig.json":
            continue
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(mode):
            continue
        for directory, dirs, files, fd in os.fwalk(path, onerror=raise_walk_error, follow_symlinks=False):
            for entry in dirs + files:
                if stat.S_ISLNK(os.stat(entry, dir_fd=fd, follow_symlinks=False).st_mode):
                    raise _reject_source_link(str((Path(directory) / entry).relative_to(root)))


def _checkout_file(root: Path, name: str, *, allow_links: bool = False, read_text: bool = False):
    """Open only checkout-relative components and bind the bytes and mode read."""
    root = root.absolute()
    pending = list(reversed(Path(name).parts))
    links = []
    try:
        with ExitStack() as stack:
            directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            stack.callback(os.close, directory)
            parents = [directory]
            while pending:
                part = pending.pop()
                if part == "..":
                    if len(parents) == 1:
                        raise _reject_source_link(name)
                    parents.pop()
                    continue
                directory = parents[-1]
                mode = os.stat(part, dir_fd=directory, follow_symlinks=False).st_mode
                if stat.S_ISLNK(mode):
                    if not allow_links or len(links) == 40:
                        raise _reject_source_link(name)
                    link = os.readlink(part, dir_fd=directory)
                    links.append(link)
                    target = Path(link)
                    if target.is_absolute():
                        if not target.is_relative_to(root):
                            raise _reject_source_link(name)
                        target = target.relative_to(root)
                        parents = parents[:1]
                    pending.extend(reversed(target.parts))
                elif pending and stat.S_ISDIR(mode):
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                    stack.callback(os.close, child)
                    parents.append(child)
                elif not pending and stat.S_ISREG(mode):
                    fd = os.open(part, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                    with os.fdopen(fd, "rb") as stream:
                        before = os.fstat(stream.fileno())
                        if not stat.S_ISREG(before.st_mode):
                            raise ReceiptError(f"checkout file changed type while reading {name}; retry with a stable checkout")
                        value = stream.read().decode() if read_text else hashlib.file_digest(stream, "sha256").hexdigest()
                        after = os.fstat(stream.fileno())
                        if (before.st_mtime_ns, before.st_ctime_ns) != (after.st_mtime_ns, after.st_ctime_ns):
                            raise ReceiptError(f"checkout file changed while reading {name}; retry with a stable checkout")
                        if read_text:
                            return value
                        return {"links": links, "executable": before.st_mode & 0o111, "sha256": value}
                else:
                    return {"links": links, "type": stat.S_IFMT(mode)}
            return {"links": links, "type": stat.S_IFDIR}
    except FileNotFoundError:
        return {"links": links}
    except OSError as exc:
        raise ReceiptError(f"cannot fingerprint checkout path {name}; check its permissions and replace any symlink with an in-checkout file") from exc


def dirty_path_digest(root: Path, paths: list[str], *, allow_links: bool = False) -> str:
    return sha256_json({name: _checkout_file(root, name, allow_links=allow_links) for name in paths})


def current_identity(root: Path = ROOT, model: dict | None = None) -> dict:
    _check_source_links(root)
    dirty = dirty_paths(root)
    identity = {
        "commit": _git(root, "rev-parse", "HEAD").decode().strip(),
        "dirty": bool(dirty),
        "dirty_paths": dirty,
        "inputs": {name: _checkout_file(root, name).get("sha256", "MISSING")
                   for name in IDENTITY_INPUTS},
        "runtime": {"python": platform.python_version(), "node": node_version(),
                    "platform": f"{platform.system()}-{platform.machine()}"},
        "model": model,
    }
    if dirty:
        identity["dirty_source_sha256"] = dirty_path_digest(root, [name for name in dirty
            if name.startswith(("src/", "scripts/")) or name == "tsconfig.json"])
    return identity


def approved_model_sha256(root: Path = ROOT) -> str:
    """Single source of truth: the constant the retrieval code enforces."""
    return _model_sha256("APPROVED_MODEL_SHA256", root)


def approved_reranker_sha256(root: Path = ROOT) -> str:
    return _model_sha256("RERANK_MODEL_SHA256", root)


def _model_sha256(name: str, root: Path) -> str:
    text = _checkout_file(root, "src/retrieval/offline.ts", read_text=True)
    if not isinstance(text, str):
        raise ReceiptError("missing regular source file src/retrieval/offline.ts")
    match = re.search(rf'\b{name}\s*=\s*"([0-9a-f]{{64}})"', text)
    if not match:
        raise ReceiptError(f"{name} not found in src/retrieval/offline.ts")
    return match.group(1)


def identity_key(identity: dict) -> dict:
    """Fields that must match for evidence to be current (dirty paths excluded)."""
    return {k: identity[k] for k in ("commit", "inputs", "runtime")}


def validate_receipt(receipt: dict) -> None:
    def need(cond, msg):
        if not cond:
            raise ReceiptError(msg)
    need(isinstance(receipt, dict), "receipt is not an object")
    need(receipt.get("schema") == RECEIPT_SCHEMA, "wrong or missing schema")
    need(receipt.get("tier") in TIERS, "invalid tier")
    for key in ("run_id", "started", "finished"):
        need(isinstance(receipt.get(key), str) and receipt[key], f"missing {key}")
    ident = receipt.get("identity")
    need(isinstance(ident, dict), "missing identity")
    need(isinstance(ident.get("commit"), str) and re.fullmatch(r"[0-9a-f]{40}", ident["commit"] or ""), "bad commit")
    need(isinstance(ident.get("dirty"), bool), "bad dirty flag")
    need(isinstance(ident.get("inputs"), dict) and set(ident["inputs"]) == set(IDENTITY_INPUTS), "bad inputs")
    need(isinstance(ident.get("runtime"), dict), "bad runtime")
    if receipt["tier"] == "b":
        model = ident.get("model")
        need(isinstance(model, dict) and re.fullmatch(r"[0-9a-f]{64}", model.get("sha256", "")), "tier b needs model hash")
    commands = receipt.get("commands")
    need(isinstance(commands, list) and commands, "missing commands")
    for c in commands:
        need(isinstance(c.get("argv"), list) and isinstance(c.get("exit"), int), "bad command record")
    need(isinstance(receipt.get("repeat"), int) and receipt["repeat"] >= 1, "bad repeat")
    need(isinstance(receipt.get("deterministic"), bool), "bad deterministic flag")
    outcomes = receipt.get("outcomes")
    need(isinstance(outcomes, list), "missing outcomes")
    ids = set()
    for o in outcomes:
        need(isinstance(o.get("id"), str) and o.get("outcome") in OUTCOMES, "bad outcome record")
        need(o["id"] not in ids, f"duplicate outcome id {o['id']}")
        ids.add(o["id"])
    need(receipt.get("outcomes_sha256") == sha256_json(outcomes), "outcomes digest mismatch")
    if "measurement" in receipt:
        measurement = receipt["measurement"]
        need(isinstance(measurement, dict), "bad measurement")
        need(isinstance(measurement.get("check"), str) and ids == {measurement["check"]},
             "measurement must match its outcome id")
        digest = measurement.get("report_sha256")
        need(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest), "bad measurement report hash")
        need(receipt["deterministic"], "measurement outcome must be complete")


def write_measurement(check: str, identity: dict, started: str, report: Path,
                      passed: bool, argv: list[str], *, report_sha256: str | None = None) -> Path:
    if report_sha256 is None:
        report_sha256 = sha256_file(report)
    finished = datetime.now(timezone.utc).isoformat()
    run_id = str(uuid.uuid4())
    outcomes = [{"id": check, "outcome": "passed" if passed else "failed"}]
    receipt = {"schema": RECEIPT_SCHEMA, "tier": "b", "run_id": run_id, "started": started,
               "finished": finished, "identity": identity, "repeat": 1, "deterministic": True,
               "commands": [{"argv": argv, "exit": 0 if passed else 1}],
               "outcomes": outcomes, "outcomes_sha256": sha256_json(outcomes),
               "measurement": {"check": check, "report_sha256": report_sha256}}
    validate_receipt(receipt)
    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    path = RECEIPT_DIR / f"{finished.replace(':', '')}-tier-b-{run_id[:8]}.json"
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as target:
        temporary = Path(target.name)
        try:
            target.write(json.dumps(receipt, indent=1) + "\n")
            target.flush()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return path


def load_receipts(directory: Path = RECEIPT_DIR) -> tuple[list[dict], list[str]]:
    receipts, problems = [], []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        try:
            receipt = json.loads(path.read_text())
            validate_receipt(receipt)
            receipts.append(receipt)
        except (ReceiptError, json.JSONDecodeError, AttributeError, TypeError) as exc:
            problems.append(f"{path.name}: {exc}")
    return receipts, problems


def load_gates(path: Path = GATES_FILE) -> list[dict]:
    data = json.loads(path.read_text())
    if data.get("schema") != GATES_SCHEMA:
        raise ReceiptError("gates.json: wrong schema")
    seen = set()
    for gate in data["gates"]:
        for check in gate["checks"]:
            if check["id"] in seen or check["tier"] not in TIERS:
                raise ReceiptError(f"gates.json: bad or duplicate check {check['id']}")
            if "measurement" in check and (check["measurement"] is not True or check.get("tests")):
                raise ReceiptError(f"gates.json: invalid measurement check {check['id']}")
            seen.add(check["id"])
    return data["gates"]


def _matches(test_id: str, selector: str) -> bool:
    return test_id == selector or test_id.startswith(selector)


def check_status(check: dict, receipts: list[dict], current: dict) -> tuple[str, str]:
    selectors = check.get("tests", [])
    measurement = check["id"] if check.get("measurement") else None
    if not selectors and measurement is None:
        return "MISSING", "no automated check implemented yet"
    tier = [r for r in receipts if r["tier"] == check["tier"]
            and (r.get("measurement") or {}).get("check") == measurement]
    if not tier:
        return "MISSING", f"no tier {check['tier']} receipt"
    key = identity_key(current)
    matching = [r for r in tier if identity_key(r["identity"]) == key]
    if not matching:
        return "STALE", f"tier {check['tier']} receipts are from other code/inputs/runtime"
    clean = [r for r in matching if not r["identity"]["dirty"]]
    if not clean:
        return "EXPLORATORY", "only dirty-tree receipts exist; commit and rerun"
    receipt = max(clean, key=lambda r: r["finished"])
    if receipt["tier"] == "b":
        # current["model"] carries the approved hash the code enforces.
        model = receipt["identity"].get("model") or {}
        if model.get("sha256") != (current.get("model") or {}).get("sha256"):
            return "STALE", "model hash differs from the approved model"
    if measurement:
        outcome = receipt["outcomes"][0]["outcome"]
        status = {"passed": "PASS", "failed": "FAIL", "error": "FAIL", "skipped": "MISSING"}[outcome]
        return status, f"measurement run {receipt['run_id']}"
    selected = [o for o in receipt["outcomes"] if any(_matches(o["id"], s) for s in selectors)]
    if not selected:
        return "MISSING", "receipt contains no matching tests"
    if not receipt["deterministic"]:
        return "FAIL", f"run {receipt['run_id']}: outcomes differed between repeats"
    bad = [o["id"] for o in selected if o["outcome"] in ("failed", "error")]
    if bad:
        return "FAIL", f"{len(bad)} failing: {bad[0]}" + (" ..." if len(bad) > 1 else "")
    skipped = [o["id"] for o in selected if o["outcome"] == "skipped"]
    if skipped:
        return "MISSING", f"{len(skipped)} skipped: {skipped[0]}"
    return "PASS", f"{len(selected)} tests, run {receipt['run_id']}"


def evaluate(gates: list[dict], receipts: list[dict], current: dict) -> list[dict]:
    rows = []
    for gate in gates:
        for check in gate["checks"]:
            status, detail = check_status(check, receipts, current)
            rows.append({"gate": gate["gate"], "check": check["id"], "tier": check["tier"],
                         "status": status, "detail": detail})
    return rows


def exit_code(rows: list[dict], problems: list[str]) -> int:
    if any(r["status"] == "FAIL" for r in rows) or problems:
        return 1
    return 0 if rows and all(r["status"] == "PASS" for r in rows) else 2


if __name__ == "__main__":
    sys.exit("use run_tier.py or check_gates.py")
