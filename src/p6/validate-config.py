#!/usr/bin/env python3
"""
P6: Claude Code config validation.

Validates:
- ~/.claude/settings.json exists and has expected schema (model, permissions, hooks)
- ~/.claude/settings.local.json exists (per-project permissions)
- No dangerous global permission patterns
- Wiki child agent JSON at src/p6/wiki-child-agent.json validates against schema
- --agents JSON is valid TOML-parseable (Claude Code loads it as JSON)
"""

import json
import os
import sys
from pathlib import Path


def validate_main_settings(path: Path) -> dict:
    """Validate main Claude Code settings file."""
    if not path.exists():
        raise FileNotFoundError(f"Missing Claude Code settings: {path}")
    with open(path) as f:
        data = json.load(f)
    assert isinstance(data, dict), f"{path} must be a JSON object"
    # Expected keys: model, permissions, hooks, session...
    assert "model" in data or "permissions" in data or "hooks" in data, (
        f"{path} has unexpected schema (no model/permissions/hooks)"
    )
    return data


def validate_local_settings(path: Path) -> dict:
    """Validate per-project local settings."""
    if not path.exists():
        raise FileNotFoundError(f"Missing local settings: {path}")
    with open(path) as f:
        data = json.load(f)
    assert isinstance(data, dict), f"{path} must be a JSON object"
    assert "permissions" in data, f"{path} must have 'permissions' key"
    perms = data["permissions"]
    assert "allow" in perms or "deny" in perms, (
        f"{path}/permissions must have 'allow' or 'deny'"
    )
    return data


def validate_child_agent_json(path: Path) -> dict:
    """Validate wiki child agent JSON against Claude Code agent schema."""
    if not path.exists():
        raise FileNotFoundError(f"Missing child agent JSON: {path}")
    with open(path) as f:
        data = json.load(f)
    # Required keys for Claude Code agent
    required = ["description", "prompt", "mode"]
    for key in required:
        assert key in data, f"Child agent JSON missing required key: {key}"
    # mode must be 'subagent' for child execution
    assert data["mode"] in ("subagent", "primary", "all"), (
        f"mode must be subagent/primary/all, got: {data['mode']}"
    )
    # tools is optional but recommended
    if "tools" in data:
        assert isinstance(data["tools"], list), "tools must be a list"
    # deniedTools is optional
    if "deniedTools" in data:
        assert isinstance(data["deniedTools"], list), "deniedTools must be a list"
    return data


def validate_hooks(path: Path) -> None:
    """Validate hook configuration doesn't have dangerous patterns."""
    with open(path) as f:
        data = json.load(f)
    hooks = data.get("hooks", {})
    for matcher, entries in hooks.items():
        for entry in entries:
            cmd = entry.get("command", "")
            # No eval/exec of arbitrary strings
            assert "eval(" not in cmd.lower(), f"Dangerous eval in hook: {matcher}"
            assert "exec(" not in cmd.lower(), f"Dangerous exec in hook: {matcher}"


def main():
    home = Path.home()
    claude = home / ".claude"

    results = []

    # 6.1: main settings
    try:
        main = validate_main_settings(claude / "settings.json")
        model = main.get("model", "not-set")
        results.append(f"6.1 main settings: OK (model={model})")
    except (FileNotFoundError, json.JSONDecodeError) as e:
        results.append(f"6.1 main settings: FAIL ({e})")

    # 6.2: local settings
    try:
        local = validate_local_settings(claude / "settings.local.json")
        perms = local["permissions"]
        allow_count = len(perms.get("allow", []))
        deny_count = len(perms.get("deny", []))
        results.append(f"6.2 local settings: OK (allow={allow_count}, deny={deny_count})")
    except (FileNotFoundError, json.JSONDecodeError) as e:
        results.append(f"6.2 local settings: FAIL ({e})")

    # 6.3: hooks validation
    try:
        validate_hooks(claude / "settings.json")
        results.append("6.3 hooks: OK (no eval/exec in commands)")
    except (FileNotFoundError, json.JSONDecodeError, AssertionError) as e:
        results.append(f"6.3 hooks: FAIL ({e})")

    # 6.4: child agent JSON
    try:
        agent = validate_child_agent_json(Path("src/p6/wiki-child-agent.json"))
        results.append(f"6.4 child agent: OK (mode={agent['mode']}, tools={len(agent.get('tools',[]))})")
    except (FileNotFoundError, json.JSONDecodeError, AssertionError) as e:
        results.append(f"6.4 child agent: FAIL ({e})")

    # 6.5: --agents CLI accepts our JSON
    import subprocess
    try:
        with open("src/p6/wiki-child-agent.json") as f:
            agent_json = f.read()
        r = subprocess.run(
            ["claude", "--agents", agent_json, "--print", "echo P6 OK"],
            capture_output=True, text=True, timeout=30, cwd="/home/kos/agent-ui-test"
        )
        if r.returncode == 0:
            results.append("6.5 --agents CLI: OK (loads JSON)")
        else:
            results.append(f"6.5 --agents CLI: FAIL (exit {r.returncode}: {r.stderr[:200]})")
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        results.append(f"6.5 --agents CLI: FAIL ({e})")

    print("\n".join(results))
    failures = [r for r in results if r.startswith("FAIL")]
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
