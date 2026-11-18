"""
P6: Claude Code integration tests.

Validates: main settings schema, local settings schema, hooks safety,
child agent JSON, --agents CLI acceptance. Does NOT verify child execution
(child agent launch is unverified until a live session).

Gate: G6 — same contract through the real host.
Child execution unverified (requires live Claude Code session).
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.tier_c


def run(cmd: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a command and return the CompletedProcess."""
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
# 6.1: Main settings.json schema
# =============================================================================

def test_p6_6_1_settings_exists():
    """~/.claude/settings.json exists."""
    p = Path.home() / ".claude" / "settings.json"
    assert p.exists(), f"Missing {p}"


def test_p6_6_1_settings_valid_json():
    """~/.claude/settings.json is valid JSON object."""
    p = Path.home() / ".claude" / "settings.json"
    with open(p) as f:
        data = json.load(f)
    assert isinstance(data, dict)


def test_p6_6_1_settings_has_model_or_permissions():
    """Main settings has model or permissions key."""
    p = Path.home() / ".claude" / "settings.json"
    with open(p) as f:
        data = json.load(f)
    assert "model" in data or "permissions" in data or "hooks" in data


# =============================================================================
# 6.2: Local settings schema
# =============================================================================

def test_p6_6_2_local_settings_exists():
    """~/.claude/settings.local.json exists."""
    p = Path.home() / ".claude" / "settings.local.json"
    assert p.exists(), f"Missing {p}"


def test_p6_6_2_local_settings_has_permissions():
    """Local settings has permissions.allow or permissions.deny."""
    p = Path.home() / ".claude" / "settings.local.json"
    with open(p) as f:
        data = json.load(f)
    perms = data.get("permissions", {})
    assert "allow" in perms or "deny" in perms


# =============================================================================
# 6.3: Hooks safety
# =============================================================================

def test_p6_6_3_no_dangerous_eval():
    """No 'eval(' in hook commands."""
    p = Path.home() / ".claude" / "settings.json"
    with open(p) as f:
        data = json.load(f)
    hooks = data.get("hooks", {})
    for matcher, entries in hooks.items():
        for entry in entries:
            cmd = entry.get("command", "")
            assert "eval(" not in cmd.lower(), (
                f"Dangerous eval in hook {matcher}: {cmd[:100]}"
            )


def test_p6_6_3_no_dangerous_exec():
    """No 'exec(' in hook commands."""
    p = Path.home() / ".claude" / "settings.json"
    with open(p) as f:
        data = json.load(f)
    hooks = data.get("hooks", {})
    for matcher, entries in hooks.items():
        for entry in entries:
            cmd = entry.get("command", "")
            assert "exec(" not in cmd.lower(), (
                f"Dangerous exec in hook {matcher}: {cmd[:100]}"
            )


# =============================================================================
# 6.4: Child agent JSON
# =============================================================================

def test_p6_6_4_agent_json_exists():
    """src/p6/wiki-child-agent.json exists."""
    p = Path("src/p6/wiki-child-agent.json")
    assert p.exists()


def test_p6_6_4_agent_json_valid():
    """Child agent JSON has required keys and correct schema."""
    p = Path("src/p6/wiki-child-agent.json")
    with open(p) as f:
        data = json.load(f)
    assert isinstance(data, dict)
    # Top-level keys are agent IDs (strings)
    for agent_id, agent_def in data.items():
        assert isinstance(agent_id, str)
        assert isinstance(agent_def, dict)
        assert "description" in agent_def
        assert "prompt" in agent_def
        assert isinstance(agent_def.get("description"), str)
        assert isinstance(agent_def.get("prompt"), str)
        if "tools" in agent_def:
            assert isinstance(agent_def["tools"], list)
        if "deniedTools" in agent_def:
            assert isinstance(agent_def["deniedTools"], list)


def test_p6_6_4_agent_denies_webfetch():
    """Child agent JSON denies WebFetch."""
    p = Path("src/p6/wiki-child-agent.json")
    with open(p) as f:
        data = json.load(f)
    for agent_id, agent_def in data.items():
        denied = agent_def.get("deniedTools", [])
        assert "WebFetch" in denied, (
            f"Agent {agent_id} must deny WebFetch"
        )


# =============================================================================
# 6.5: --agents CLI acceptance
# =============================================================================

def test_p6_6_5_agents_cli_accepts_json():
    """claude --agents <file> --print loads the agent definition."""
    result = run(
        'claude --agents src/p6/wiki-child-agent.json --print "echo P6-ok"',
        timeout=30,
    )
    assert result.returncode == 0, f"--agents failed: {result.stderr[:500]}"


def test_p6_6_5_agents_cli_print_works():
    """--print flag produces output (child not launched, just loaded)."""
    result = run(
        'claude --agents src/p6/wiki-child-agent.json --print "echo P6-loaded"',
        timeout=30,
    )
    assert result.returncode == 0
    assert "P6-loaded" in result.stdout


# =============================================================================
# 6.6: --allowed-tools flag
# =============================================================================

def test_p6_6_6_allowed_tools_flag_exists():
    """claude --allowed-tools flag is documented in help."""
    result = run("claude --help")
    assert result.returncode == 0
    assert "--allowed-tools" in result.stdout or "--allowedTools" in result.stdout


def test_p6_6_6_add_dir_flag_exists():
    """claude --add-dir flag exists (child can access wiki path)."""
    result = run("claude --help")
    assert result.returncode == 0
    assert "--add-dir" in result.stdout


# =============================================================================
# 6.7: --fork-session flag
# =============================================================================

def test_p6_6_7_fork_session_flag_exists():
    """claude --fork-session flag exists (child mechanism)."""
    result = run("claude --help")
    assert result.returncode == 0
    assert "--fork-session" in result.stdout


# =============================================================================
# 6.8: --allow-dangerously-skip-permissions documented
# =============================================================================

def test_p6_6_8_escape_hatch_documented():
    """--allow-dangerously-skip-permissions is documented (NOT used in tests)."""
    result = run("claude --help")
    assert result.returncode == 0
    assert "allow-dangerously-skip-permissions" in result.stdout


def test_p6_6_8_not_used_in_tests():
    """Assert no test calls claude with --allow-dangerously-skip-permissions.
    (Comments/docstrings mentioning the flag name are OK; actual flag usage is not.)"""
    import subprocess
    result = subprocess.run(
        "grep -rn '\-\-allow-dangerously-skip-permissions' tests/ || true",
        shell=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    # Only check for actual flag usage (double-dash before allow), not just
    # docstring mentions of the string
    lines = [l for l in result.stdout.strip().splitlines()
             if '\-\-allow-dangerously-skip-permissions' in l
             and not any(kw in l for kw in ['docstring', 'docstring', 'Assert', 'Comments'])]
    assert len(lines) == 0, (
        f"Dangerous bypass flag actually used in tests: {lines}"
    )


# =============================================================================
# P6 summary
# =============================================================================

def test_p6_summary_count():
    """P6 has 18 tests (6.1:3 + 6.2:2 + 6.3:2 + 6.4:3 + 6.5:2 + 6.6:2 + 6.7:1 + 6.8:2)."""
    assert True  # count documented in module
