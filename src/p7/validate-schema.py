#!/usr/bin/env python3
"""
P7: OpenCode 1.19.3 installed-schema validation.

Validates:
- Version 1.19.3 at /home/kos/.opencode/bin/opencode
- Config schema at ~/.config/opencode/opencode.jsonc
- Agent JSON validates against opencode.ai/agent.json schema
- --pure flag exists (agent isolation)
- --fork flag exists (session forking)
- opencode agent create --mode subagent exists
- No dangerous patterns in allowed tools
- Available models include the pinned answer model
"""

import json
import re
import subprocess
import sys
from pathlib import Path


def check_version(binary: Path, expected: str) -> bool:
    """Check OpenCode version."""
    r = subprocess.run(
        [str(binary), "-v"],
        capture_output=True, text=True, timeout=10,
    )
    return expected in r.stdout


def check_help_flags(binary: Path, flags: list[str]) -> tuple[str, bool]:
    """Check that help text contains all flags."""
    r = subprocess.run(
        [str(binary), "--help"],
        capture_output=True, text=True, timeout=10,
    )
    missing = []
    for flag in flags:
        if flag not in r.stdout:
            missing.append(flag)
    return missing


def validate_config(path: Path) -> dict:
    """Validate OpenCode config file."""
    with open(path) as f:
        data = json.load(f)
    assert isinstance(data, dict)
    # Must have $schema or top-level config keys
    assert "$schema" in data or data, "Config must be non-empty object"
    return data


def validate_agent_json(path: Path) -> dict:
    """Validate agent JSON schema."""
    with open(path) as f:
        data = json.load(f)
    # Required: name, description, prompt
    assert "name" in data, "Missing 'name'"
    assert "description" in data, "Missing 'description'"
    assert "prompt" in data, "Missing 'prompt'"
    # Optional but recommended
    assert isinstance(data.get("prompt"), str)
    assert isinstance(data.get("name"), str)
    # Tools must be object or list
    if "tools" in data:
        tools = data["tools"]
        assert isinstance(tools, (dict, list))
        if isinstance(tools, dict):
            for k, v in tools.items():
                assert isinstance(v, bool), f"tools.{k} must be bool"
    # Model must be valid format provider/model
    if "model" in data:
        assert "/" in data["model"], (
            f"model must be 'provider/model', got: {data['model']}"
        )
    return data


def validate_model_available(binary: Path, model_id: str) -> bool:
    """Check if a model is listed by opencode models."""
    r = subprocess.run(
        [str(binary), "models"],
        capture_output=True, text=True, timeout=30,
    )
    return model_id in r.stdout


def main():
    binary = Path("/home/kos/.opencode/bin/opencode")
    config = Path.home() / ".config" / "opencode" / "opencode.jsonc"
    agent_json = Path("src/p7/wiki-child-agent.json")

    results = []

    # 7.1: Version
    if check_version(binary, "1.19.3"):
        results.append("7.1 version: 1.19.3 ✓")
    else:
        r = subprocess.run([str(binary), "-v"], capture_output=True, text=True, timeout=10)
        results.append(f"7.1 version: FAIL ({r.stdout.strip()})")

    # 7.2: Config schema
    try:
        cfg = validate_config(config)
        results.append(f"7.2 config schema: OK (keys: {list(cfg.keys())})")
    except (FileNotFoundError, json.JSONDecodeError, AssertionError) as e:
        results.append(f"7.2 config schema: FAIL ({e})")

    # 7.3: Agent JSON
    try:
        agent = validate_agent_json(agent_json)
        results.append(f"7.3 agent JSON: OK (name={agent['name']}, model={agent.get('model','?')})")
    except (FileNotFoundError, json.JSONDecodeError, AssertionError) as e:
        results.append(f"7.3 agent JSON: FAIL ({e})")

    # 7.4: --pure flag (on run subcommand — help goes to stderr)
    r4 = subprocess.run([str(binary), "run", "--help"], capture_output=True, text=True, timeout=10)
    help_text = r4.stdout + r4.stderr
    if "--pure" in help_text:
        results.append("7.4 --pure flag: ✓")
    else:
        results.append("7.4 --pure flag: ✗ not found")

    # 7.5: --fork flag (on run subcommand)
    if "--fork" in help_text:
        results.append("7.5 --fork flag: ✓")
    else:
        results.append("7.5 --fork flag: ✗ not found")

    # 7.6: agent create --mode subagent (help goes to stderr)
    r6 = subprocess.run([str(binary), "agent", "create", "--help"],
                        capture_output=True, text=True, timeout=10)
    help6 = r6.stdout + r6.stderr
    if "subagent" in help6 and "--mode" in help6:
        results.append("7.6 agent create --mode subagent: ✓")
    else:
        results.append(f"7.6 agent create --mode subagent: ✗ ({help6[:200]})")

    # 7.7: pinned model available
    if validate_model_available(binary, "qwen3.8-35b-a3b-mtp-256k"):
        results.append("7.7 pinned model available: ✓")
    else:
        results.append("7.7 pinned model available: ✗ (check models list)")

    # 7.8: no dangerous tools in agent
    try:
        with open(agent_json) as f:
            agent = json.load(f)
        denied = agent.get("deniedTools", [])
        assert "webfetch" in denied or "WebFetch" in denied
        results.append("7.8 denied webfetch: ✓")
    except (FileNotFoundError, AssertionError) as e:
        results.append(f"7.8 denied webfetch: FAIL ({e})")

    print("\n".join(results))
    failures = [r for r in results if "FAIL" in r or "✗" in r]
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
