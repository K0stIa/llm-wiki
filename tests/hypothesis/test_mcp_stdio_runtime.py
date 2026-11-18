"""Actual MCP initialize/list/call operations, not handler mocks."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.authority.authority import connect_knowledge


def client(database, project, calls=(), principal="worker"):
    request = {"database": str(database), "project": project, "principal": principal, "calls": calls}
    run = subprocess.run(["node", str(ROOT / "tests/runtime/mcp-client.mjs")],
                         input=json.dumps(request), text=True, capture_output=True, cwd=ROOT, timeout=45)
    assert run.returncode == 0, run.stdout + run.stderr
    return json.loads(run.stdout)


def call(name, **args):
    return {"name": name, "arguments": args}


def value(result):
    assert not result.get("isError"), result
    return json.loads(result["content"][0]["text"])


@pytest.fixture
def vault(tmp_path):
    path = tmp_path / "synthetic.db"
    first = connect_knowledge(str(path), "alpha")
    alpha = first.create_page("alpha", "shared", "Alpha", "synthetic alpha durable fact " * 6, "owner")
    second = connect_knowledge(str(path), "beta")
    beta = second.create_page("beta", "secret", "Beta", "synthetic beta secret", "owner")
    return path, alpha, beta


def test_real_worker_boundary(vault):
    database, alpha, beta = vault
    result = client(database, "alpha", [
        call("wiki_page", page="shared"),
        call("wiki_page", page="secret"),
        call("wiki_page", page="shared", revision=beta.revision),
        call("wiki_page", page="shared", project="beta"),
        call("wiki_page", page="shared", principal="curator"),
        call("wiki_curator_pending"),
    ])
    names = {tool["name"] for tool in result["tools"]}
    assert names == {"wiki_page", "wiki_read", "wiki_recall", "wiki_propose", "wiki_operation"}
    assert value(result["results"][0])["markdown"] == alpha.markdown
    for denied in result["results"][1:]:
        assert denied.get("isError"), denied


def test_durable_proposal_curator_publish_and_fresh_connection(vault):
    database, alpha, beta = vault
    body = "Full child-written synthetic body with a unique tail " * 4
    receipt = value(client(database, "alpha", [call("wiki_propose", page="shared",
                    baseRevision=alpha.revision, changeKind="replace", title="Update",
                    markdown=body, key="child-key")])["results"][0])
    assert receipt["kind"] == "pending"
    # Worker cannot publish; a separate launch-bound curator may review and decide.
    pending = value(client(database, "alpha", [call("wiki_curator_pending")], "curator")["results"][0])
    assert pending["items"][0]["body"] == body
    denied = client(database, "beta", [call("wiki_curator_decide", proposalKey="child-key",
                    digest=pending["items"][0]["reviewDigest"], decision="publish")], "curator")
    assert denied["results"][0].get("isError")
    denied = client(database, "alpha", [call("wiki_curator_decide", proposalKey="child-key",
                    digest="wrong", decision="publish")], "curator")
    assert denied["results"][0].get("isError")
    published = value(client(database, "alpha", [call("wiki_curator_decide", proposalKey="child-key",
                      digest=pending["items"][0]["reviewDigest"], decision="publish")], "curator")["results"][0])
    assert published["kind"] == "committed"
    fresh = client(database, "alpha", [call("wiki_page", page="shared")])
    assert value(fresh["results"][0])["markdown"] == body
    assert value(client(database, "beta", [call("wiki_operation", key="child-key")])["results"][0]) == {"kind": "unknown"}


def test_current_scoped_lexical_recall_and_byte_cap(vault):
    database, alpha, beta = vault
    result = client(database, "alpha", [call("wiki_recall", query="synthetic alpha", maxBytes=24000),
                      call("wiki_recall", query="synthetic beta", maxBytes=2048),
                      call("wiki_recall", query="alpha", coverage="require-hybrid-current")])
    first = value(result["results"][0])
    assert first["coverage"] == "lexical-only"
    assert first["evidence"]["passages"][0]["revision"] == alpha.revision
    assert all(p["page"] != "secret" for p in first["evidence"]["passages"])
    bounded = value(result["results"][1])
    assert len(json.dumps(bounded, ensure_ascii=False).encode()) <= 2048
    assert value(result["results"][2])["kind"] == "not-ready"
