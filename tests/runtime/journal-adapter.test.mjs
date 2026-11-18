// G1: host-call journal through the actual Pi adapter code (src/pi/wiki-journal.ts).
// The journal and authority are real processes and real SQLite files. Crashes are
// named fault points (exit 97, no reply). "Restart" = a new adapter call that runs
// recovery first, exactly what the extension does on session_start.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { journaledProposeTool, recoverJournal, enrollJournal } from '../../src/pi/wiki-journal.ts';
import { proposeSchema } from '../../src/pi/wiki-mcp-extension.ts';

const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const AUTHORITY = join(ROOT, 'src/authority');

function python(code, ...args) {
  return execFileSync('python3', ['-c', code, ...args], { encoding: 'utf8', cwd: AUTHORITY }).trim();
}

function seed() {
  const dir = mkdtempSync(join(tmpdir(), 'wiki-journal-'));
  const database = join(dir, 'authority.sqlite');
  const base = python(`import sys
from authority import connect_knowledge
s=connect_knowledge(sys.argv[1],'alpha'); print(s.create_page('alpha','page','Title','Original','owner').revision)`, database);
  const binding = { journal: join(dir, 'journal.sqlite'), database, project: 'alpha' };
  return { dir, database, base, binding };
}

function rows(database, sql) {
  return JSON.parse(python(`import json,sqlite3,sys
c=sqlite3.connect(sys.argv[1]); print(json.dumps(c.execute(sys.argv[2]).fetchall()))`, database, sql));
}

const args = (base, markdown = 'Corrected body') =>
  ({ page: 'page', baseRevision: base, changeKind: 'replace', title: 'Title', markdown });
const ctx = (session) => ({ sessionManager: { getSessionId: () => session } });

async function withFault(point, fn) {
  process.env.WIKI_TEST_FAULT_POINT = point;
  try { return await fn(); } finally { delete process.env.WIKI_TEST_FAULT_POINT; }
}

test('Pi tool derives the key from session id + toolCallId; retries are idempotent', async () => {
  const { dir, database, base, binding } = seed();
  try {
    await enrollJournal(binding);
    const tool = journaledProposeTool(binding, proposeSchema);
    const first = await tool.execute('call-1', args(base), undefined, undefined, ctx('session-A'));
    assert.equal(first.details.kind, 'pending');
    assert.match(first.details.key, /^host-[0-9a-f]{64}$/);
    const again = await tool.execute('call-1', args(base), undefined, undefined, ctx('session-A'));
    assert.deepEqual(again.details, first.details);
    // Same call identity, different payload: the journal refuses, the authority is untouched.
    await assert.rejects(tool.execute('call-1', args(base, 'other'), undefined, undefined, ctx('session-A')));
    // A different host call is a different operation (no semantic deduplication is claimed).
    const other = await tool.execute('call-2', args(base), undefined, undefined, ctx('session-A'));
    assert.notEqual(other.details.proposal, first.details.proposal);
    assert.deepEqual(rows(database, "SELECT COUNT(*), MIN(principal), MAX(principal) FROM operations"), [[2, 'worker', 'worker']]);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test('model-supplied key or epoch and missing host identity are refused', async () => {
  const { dir, database, base, binding } = seed();
  try {
    await enrollJournal(binding);
    const tool = journaledProposeTool(binding, proposeSchema);
    await assert.rejects(tool.execute('c', { ...args(base), key: 'mine' }, undefined, undefined, ctx('s')), /host-derived/);
    await assert.rejects(tool.execute('c', { ...args(base), expectedEpoch: 'e' }, undefined, undefined, ctx('s')), /host-derived/);
    await assert.rejects(tool.execute('', args(base), undefined, undefined, ctx('s')), /identity unavailable/);
    await assert.rejects(tool.execute('c', args(base), undefined, undefined, ctx('')), /identity unavailable/);
    assert.deepEqual(rows(database, 'SELECT COUNT(*) FROM proposals'), [[0]]);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test('unenrolled journal fails closed instead of auto-enrolling', async () => {
  const { dir, database, base, binding } = seed();
  try {
    const tool = journaledProposeTool(binding, proposeSchema);
    await assert.rejects(tool.execute('c', args(base), undefined, undefined, ctx('s')));
    assert.deepEqual(rows(database, 'SELECT COUNT(*) FROM proposals'), [[0]]);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

for (const [point, committed, unfinished] of [
  ['journal.after-prepare', false, true],          // crash before send
  ['rpc.after-commit-before-reply:wiki_host_propose', true, true],   // authority committed, reply lost
  ['journal.after-send', true, true],              // reply received, receipt not recorded
  ['journal.after-receipt', true, false],          // receipt recorded, adapter reply lost
]) {
  test(`crash at ${point} is recovered with the original key, exactly once`, async () => {
    const { dir, database, base, binding } = seed();
    try {
      await enrollJournal(binding);
      const tool = journaledProposeTool(binding, proposeSchema);
      await withFault(point, () => assert.rejects(
        tool.execute('call-1', args(base), undefined, undefined, ctx('session-A')), /without a reply/));
      assert.deepEqual(rows(database, 'SELECT COUNT(*) FROM proposals'), [[committed ? 1 : 0]]);
      assert.deepEqual(rows(binding.journal, 'SELECT COUNT(*) FROM calls WHERE receipt IS NULL'), [[unfinished ? 1 : 0]]);

      // Restart: recovery runs before any new call.
      const recovered = await recoverJournal(binding);
      assert.equal(recovered.length, unfinished ? 1 : 0);
      const proposals = rows(database, 'SELECT proposal_id FROM proposals');
      assert.equal(proposals.length, 1, 'recovery must admit exactly one proposal');
      const keys = rows(database, 'SELECT key FROM proposal_keys');
      const journaled = rows(binding.journal, 'SELECT request FROM calls').map(([r]) => JSON.parse(r).args.key);
      assert.deepEqual(keys.map(([k]) => k), journaled, 'authority key must be the journaled key');
      assert.deepEqual(rows(binding.journal, 'SELECT COUNT(*) FROM calls WHERE receipt IS NULL'), [[0]]);
      if (unfinished) assert.equal(recovered[0].result.proposal, proposals[0][0]);

      // The interrupted host call itself, if retried, returns the same proposal.
      const retry = await tool.execute('call-1', args(base), undefined, undefined, ctx('session-A'));
      assert.equal(retry.details.proposal, proposals[0][0]);
      assert.deepEqual(rows(database, 'SELECT COUNT(*) FROM proposals'), [[1]]);
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });
}

test('after an authority restore (new epoch) recovery fails closed, never re-keys', async () => {
  const { dir, database, base, binding } = seed();
  try {
    await enrollJournal(binding);
    const tool = journaledProposeTool(binding, proposeSchema);
    await withFault('journal.after-prepare', () => assert.rejects(
      tool.execute('call-1', args(base), undefined, undefined, ctx('session-A'))));
    python(`import sqlite3,sys
c=sqlite3.connect(sys.argv[1]); c.execute("UPDATE projects SET epoch='restored-epoch'"); c.commit()`, database);
    await assert.rejects(recoverJournal(binding), /epoch/);
    assert.deepEqual(rows(database, 'SELECT COUNT(*) FROM proposals'), [[0]]);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test('journaled MCP launch exposes no unjournaled wiki_propose', async () => {
  const { dir, database } = seed();
  const list = async (...mode) => {
    const client = new Client({ name: 'journal-test', version: '1.0.0' });
    await client.connect(new StdioClientTransport({ command: process.execPath,
      args: [join(ROOT, 'node_modules/tsx/dist/cli.mjs'), join(ROOT, 'src/mcp/stdio.ts'), database, 'alpha', 'worker', ...mode],
      stderr: 'ignore' }));
    try { return (await client.listTools()).tools.map(t => t.name).sort(); } finally { await client.close(); }
  };
  try {
    assert.deepEqual(await list(), ['wiki_operation', 'wiki_page', 'wiki_propose', 'wiki_read', 'wiki_recall']);
    assert.deepEqual(await list('journaled'), ['wiki_operation', 'wiki_page', 'wiki_read', 'wiki_recall']);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
