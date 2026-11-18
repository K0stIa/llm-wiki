#!/usr/bin/env python3
"""Bounded real Pi CLI sessions. Raw sessions/config remain in ignored .cache/."""
import argparse
import ipaddress
import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.cache/comparison'
MODEL = 'qwen3.8-35b-a3b-mtp-32k'
NPM = Path.home() / '.pi/agent/npm/node_modules'
WIKI = Path(os.environ.get('PI_WIKI_PACKAGE', NPM / '@zosmaai/pi-llm-wiki'))
BASE_CONFIG = Path.home() / '.pi/agent/models.json'


def private_endpoint(url):
    host = urlparse(url).hostname
    if host == 'localhost':
        return True
    try:
        address = ipaddress.ip_address(host or '')
    except ValueError:
        return False
    networks = ['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', 'fc00::/7']
    return address.is_loopback or any(address in ipaddress.ip_network(n) for n in networks)


def runtime_env():
    config = WORK / 'pi-config'
    config.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Copy only non-secret local configuration, never keys or OAuth credentials.
    providers = json.loads(BASE_CONFIG.read_text())['providers']
    local = providers['local-llamacpp']
    selected = [m for m in local['models'] if m['id'] == MODEL]
    assert len(selected) == 1, 'Required local model is not configured'
    assert private_endpoint(local['baseUrl']), 'Only a loopback or private-LAN inference endpoint is permitted'
    isolated = {k: local[k] for k in ['api', 'baseUrl', 'compat'] if k in local}
    isolated.update(models=selected, apiKey='local')
    (config / 'models.json').write_text(json.dumps({'providers': {'local-llamacpp': isolated}}))
    (config / 'models.json').chmod(0o600)
    (config / 'settings.json').write_text(json.dumps({'compaction': {'enabled': False}, 'retry': {'enabled': False}}))
    env = dict(os.environ)
    for key in ['PI_SESSION_ID', 'PI_SESSION_FILE', 'PI_PROVIDER', 'PI_MODEL', 'PI_REASONING_LEVEL']:
        env.pop(key, None)
    env.update(PI_CODING_AGENT_DIR=str(config), WIKI_HOME=str(WORK / 'isolated-personal'), PI_OFFLINE='1', PI_SKIP_VERSION_CHECK='1')
    return env


def run(candidate, case, prompt, write=False):
    scope = 'challenge' if case in ['q22', 'q23', 'q24', 'q25'] else 'main'
    cwd = (WORK / 'challenge' if scope == 'challenge' else WORK) / candidate
    raw_dir = WORK / 'raw-sessions' / candidate
    raw_dir.mkdir(parents=True, exist_ok=True)
    session_id = f'{case}-{time.time_ns()}'
    args = ['pi', '--offline', '--no-extensions', '--no-mcp', '--no-skills', '--no-prompt-templates',
            '--no-themes', '--no-context-files', '--no-approve', '--thinking', 'off',
            '--provider', 'local-llamacpp', '--model', MODEL, '--session-dir', str(raw_dir),
            '--session-id', session_id, '--mode', 'json']
    if candidate == 'zosma':
        tools = 'read,grep,find,ls,wiki_recall,wiki_search' + (',wiki_retro' if write else '')
        args += ['-e', str(WIKI / 'extensions/llm-wiki/index.ts'), '--tools', tools]
        args += ['--append-system-prompt', 'Use the project wiki as evidence. Call wiki_recall, then read the exact relevant files. Cite exact wiki paths. Do not invent missing evidence. Do not modify anything unless the user explicitly asks to save an insight.']
    else:
        args += ['--tools', 'read,grep,find,ls', '--append-system-prompt',
                 str(ROOT / '.cache/upstreams/nvk/profiles/query-lite/SKILL.md')]
    args += [prompt]
    before = time.monotonic()
    try:
        proc = subprocess.run(args, cwd=cwd, env=runtime_env(), text=True, capture_output=True, timeout=150)
        stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout or b''
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors='replace')
        stderr, code = '150-second experiment timeout', None
    (raw_dir / f'{session_id}.stdout.jsonl').write_text(stdout)
    (raw_dir / f'{session_id}.stderr.log').write_text(stderr)
    events = []
    for line in stdout.splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    calls = []
    assistant = []
    for event in events:
        if event.get('type') == 'tool_execution_start':
            calls.append({'name': event.get('toolName'), 'args': event.get('args')})
        if event.get('type') == 'message_end' and event.get('message', {}).get('role') == 'assistant':
            texts = [c.get('text', '') for c in event['message'].get('content', []) if c.get('type') == 'text']
            if texts:
                assistant.append('\n'.join(texts))
    record = {'candidate': candidate, 'case': case, 'scope': scope, 'model': MODEL, 'session_id': session_id,
              'exit_code': code, 'elapsed_seconds': time.monotonic() - before,
              'tool_calls': calls, 'answer': assistant[-1] if assistant else '',
              'stderr_tail': stderr[-1600:]}
    # Keep machine-local paths out of the public evidence.
    record = json.loads(json.dumps(record).replace(str(WORK), '<work>').replace(str(WIKI), '<wiki-package>').replace(str(Path.home()), '<home>'))
    path = ROOT / 'research/results/live.json'
    records = json.loads(path.read_text()) if path.exists() else []
    records.append(record)
    path.write_text(json.dumps(records, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'candidate': candidate, 'case': case, 'exit_code': code,
                      'seconds': round(record['elapsed_seconds'], 1), 'tools': [c['name'] for c in calls],
                      'answer': record['answer'], 'stderr_tail': record['stderr_tail']}, ensure_ascii=False))
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('candidate', choices=['zosma', 'nvk'])
    parser.add_argument('case', help='Fixture query ID, save, or reload')
    args = parser.parse_args()
    cases = json.loads((ROOT / 'research/fixture.json').read_text())['queries'] + json.loads((ROOT / 'research/challenge.json').read_text())['queries']
    queries = {q['id']: q for q in cases}
    if args.case == 'save':
        assert args.candidate == 'zosma', 'nvk query-lite is deliberately read-only'
        prompt = 'Save exactly one synthetic insight with wiki_retro. Slug: cross-session-check. Title: Cross-session check. Body: The invented continuity marker is amber-orbit-592. This marker is test data, not a real preference. Then report the saved path.'
        run(args.candidate, args.case, prompt, write=True)
    elif args.case == 'read-child':
        run(args.candidate, args.case, 'What marker did the child probe record, and where did it originally come from? Find and read the child probe page. Cite it and the original source. Do not guess.')
    elif args.case == 'reload':
        run(args.candidate, args.case, 'What is the invented continuity marker saved in the wiki? Search and read the source. Do not guess. Cite its exact page path.')
    else:
        run(args.candidate, args.case, queries[args.case]['query'] + ' Answer only from this synthetic project wiki and cite exact relevant page paths. If the evidence is missing, say so. Keep the answer under 120 words.')


if __name__ == '__main__':
    main()
