#!/usr/bin/env python3
"""
Capability tokens — file-based agent identity.

Replaces env vars (which die between Bash tool calls).
Tokens persist across commands, survive session restarts.

Structure:
  .pi/session_identity/agent-name/current.txt  → pointer to active token
  .pi/session_identity/agent-name/<id>.yaml    → token file (SHA256-protected)

Usage:
  python3 wiki_tokens.py init --agent my-agent
  python3 wiki_tokens.py read --agent my-agent
  python3 wiki_tokens.py verify --agent my-agent
  python3 wiki_tokens.py list
"""

import json
import os
import yaml
import hashlib
from pathlib import Path
from datetime import datetime

IDENTITY_DIR = Path.home() / ".pi" / "session_identity"

def token_dir(agent: str) -> Path:
    return IDENTITY_DIR / agent

def write_token(agent: str, data: dict) -> str:
    """Write a capability token and return its ID."""
    td = token_dir(agent)
    td.mkdir(parents=True, exist_ok=True)
    
    # Generate ID from timestamp + agent name hash
    ts = datetime.now().strftime("%Y%m%d%H%M")
    agent_hash = hashlib.md5(agent.encode()).hexdigest()[:6]
    token_id = f"{ts}-{agent_hash}"
    
    # Compute SHA256 of the token body (without checksum field)
    body = {k: v for k, v in data.items() if k != "sha256_checksum"}
    body_json = json.dumps(body, sort_keys=True)
    checksum = hashlib.sha256(body_json.encode()).hexdigest()
    data["sha256_checksum"] = checksum
    data["id"] = token_id
    data["written_at"] = datetime.now().isoformat()
    
    token_path = td / f"{token_id}.yaml"
    with open(token_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False)
    
    # Write pointer
    current_path = td / "current.txt"
    with open(current_path, "w") as f:
        f.write(token_id)
    
    return token_id

def read_token(agent: str) -> dict | None:
    td = token_dir(agent)
    if not td.exists():
        return None
    current_path = td / "current.txt"
    if not current_path.exists():
        return None
    token_id = current_path.read_text().strip()
    token_path = td / f"{token_id}.yaml"
    if not token_path.exists():
        return None
    with open(token_path) as f:
        return yaml.safe_load(f)

def verify_token(agent: str) -> bool:
    """Verify token integrity (SHA256 check)."""
    token = read_token(agent)
    if not token:
        return False
    body = {k: v for k, v in token.items() if k not in ("sha256_checksum", "id", "written_at")}
    expected = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return token.get("sha256_checksum") == expected

def list_agents() -> list[str]:
    if not IDENTITY_DIR.exists():
        return []
    return [d.name for d in IDENTITY_DIR.iterdir() if d.is_dir()]

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Capability tokens for multi-agent wiki")
    sub = parser.add_subparsers(dest="cmd")
    
    init = sub.add_parser("init")
    init.add_argument("--agent", required=True)
    init.add_argument("--groups", nargs="*", default=["all"])
    
    read = sub.add_parser("read")
    read.add_argument("--agent", required=True)
    
    verify = sub.add_parser("verify")
    verify.add_argument("--agent", required=True)
    
    sub.add_parser("list")
    
    args = parser.parse_args()
    
    if args.cmd == "init":
        token = write_token(args.agent, {
            "agent": args.agent,
            "groups": args.groups,
            "hard_walls": [],
            "contamination_quarantines": [],
            "revoked_groups": []
        })
        print(f"Token created: {token}")
        print(f"Written to: {token_dir(args.agent)}/{token}.yaml")
    
    elif args.cmd == "read":
        token = read_token(args.agent)
        if token:
            print(json.dumps(token, indent=2))
        else:
            print(f"No active token for agent: {args.agent}")
    
    elif args.cmd == "verify":
        if verify_token(args.agent):
            print(f"Token OK for agent: {args.agent}")
        else:
            print(f"Token INVALID or missing for agent: {args.agent}")
            sys.exit(1)
    
    elif args.cmd == "list":
        agents = list_agents()
        if agents:
            print("Active agents:")
            for a in agents:
                token = read_token(a)
                if token:
                    status = "OK" if verify_token(a) else "INVALID"
                    print(f"  {a}: token {token.get('id','?')} [{status}]")
        else:
            print("No agents registered.")

if __name__ == "__main__":
    main()
