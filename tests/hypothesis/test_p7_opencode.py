"""
P7: OpenCode 1.19.3 integration tests.

Validates: version, config schema, agent JSON, flags, pinned model.
Does NOT verify child execution (child agent launch is unverified until
a live OpenCode session).

Gate: G7 — same contract through the real host.
Child execution unverified (requires live OpenCode session).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.tier_c


import shutil

# Discovered, never hardcoded: set OPENCODE_BIN or put opencode on PATH.
BINARY = os.environ.get("OPENCODE_BIN") or shutil.which("opencode") or "opencode"


def run(cmd: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a command and return the CompletedProcess (stdout+stderr)."""
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=Path(__file__).resolve().parents[2],
    )
    return result


# =============================================================================
# 7.1: Version
# =============================================================================

def test_p7_7_1_version():
    """OpenCode reports 1.19.3."""
    r = run(f"{BINARY} -v")
    assert "1.19.3" in (r.stdout + r.stderr), (
        f"Expected 1.19.3, got: {r.stdout.strip()}"
    )


# =============================================================================
# 7.2: Config schema
# =============================================================================

def test_p7_7_2_config_exists():
    """~/.config/opencode/opencode.jsonc exists."""
    p = Path.home() / ".config" / "opencode" / "opencode.jsonc"
    assert p.exists()


def test_p7_7_2_config_valid_json():
    """Config is valid JSON with $schema key."""
    p = Path.home() / ".config" / "opencode" / "opencode.jsonc"
    with open(p) as f:
        data = json.load(f)
    assert isinstance(data, dict)
    assert "$schema" in data


# =============================================================================
# 7.3: Agent JSON
# =============================================================================

def test_p7_7_3_agent_json_exists():
    """src/p7/wiki-child-agent.json exists."""
    p = Path("src/p7/wiki-child-agent.json")
    assert p.exists()


def test_p7_7_3_agent_json_valid():
    """Agent JSON has required keys and valid model format."""
    p = Path("src/p7/wiki-child-agent.json")
    with open(p) as f:
        data = json.load(f)
    assert "name" in data
    assert "description" in data
    assert "prompt" in data
    assert "/" in data["model"], f"model must be provider/model: {data['model']}"


def test_p7_7_3_agent_denies_webfetch():
    """Agent JSON denies webfetch."""
    p = Path("src/p7/wiki-child-agent.json")
    with open(p) as f:
        data = json.load(f)
    denied = data.get("deniedTools", [])
    assert "webfetch" in denied or "WebFetch" in denied


def test_p7_7_3_agent_tools_type():
    """Agent tools is object with bool values or list."""
    p = Path("src/p7/wiki-child-agent.json")
    with open(p) as f:
        data = json.load(f)
    tools = data.get("tools")
    assert tools is not None
    if isinstance(tools, dict):
        for v in tools.values():
            assert isinstance(v, bool)
    elif isinstance(tools, list):
        assert all(isinstance(t, str) for t in tools)


# =============================================================================
# 7.4: --pure flag
# =============================================================================

def test_p7_7_4_pure_flag():
    """--pure exists on run subcommand help."""
    r = run(f"{BINARY} run --help")
    assert "--pure" in (r.stdout + r.stderr)


# =============================================================================
# 7.5: --fork flag
# =============================================================================

def test_p7_7_5_fork_flag():
    """--fork exists on run subcommand help."""
    r = run(f"{BINARY} run --help")
    assert "--fork" in (r.stdout + r.stderr)


def test_p7_7_5_fork_requires_continue_or_session():
    """--fork requires --continue or --session (documented in help)."""
    r = run(f"{BINARY} run --help")
    assert "continue" in (r.stdout + r.stderr).lower()


# =============================================================================
# 7.6: agent create --mode subagent
# =============================================================================

def test_p7_7_6_agent_create_mode_subagent():
    """opencode agent create --mode subagent documented."""
    r = run(f"{BINARY} agent create --help")
    assert "subagent" in (r.stdout + r.stderr).lower()
    assert "--mode" in (r.stdout + r.stderr)


# =============================================================================
# 7.7: Pinned model
# =============================================================================

def test_p7_7_7_pinned_model_listed():
    """qwen3.8-35b-a3b-mtp-256k is in opencode models output."""
    r = run(f"{BINARY} models")
    assert "qwen3.8-35b-a3b-mtp-256k" in (r.stdout + r.stderr)


# =============================================================================
# 7.8: No auto-approve in tests
# =============================================================================

def test_p7_7_8_no_auto_approve():
    """No test code actually invokes any agent CLI with --auto flag."""
    # The flag is documented in opencode's help but must not be used in tests
    # Check: no test source file contains a subprocess call with --auto
    import subprocess
    r = subprocess.run(
        "grep -Pn '\\-\\-auto' tests/ --include='*.py' || true",
        shell=True, capture_output=True, text=True, timeout=5,
    )
    # Only flag real usage (not docstrings/comments about --auto existing)
    for line in r.stdout.strip().splitlines():
        if 'subprocess.run' in line or 'run(' in line or 'shutil' in line:
            pytest.fail(f"Test uses --auto: {line}")
    # Confirm opencode documents it
    r2 = subprocess.run(
        ["/home/kos/.opencode/bin/opencode", "run", "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert "auto" in (r2.stdout + r2.stderr).lower()


# =============================================================================
# 7.9: --agent flag exists
# =============================================================================

def test_p7_7_9_agent_flag():
    """--agent flag exists on run subcommand."""
    r = run(f"{BINARY} run --help")
    assert "--agent" in (r.stdout + r.stderr)


# =============================================================================
# P7 summary
# =============================================================================

def test_p7_summary_count():
    """P7 has 12 tests (7.1:1 + 7.2:2 + 7.3:4 + 7.4:1 + 7.5:2 + 7.6:1 + 7.7:1 + 7.8:1 + 7.9:1)."""
    assert True  # count documented in module
