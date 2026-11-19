import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { evaluationRerankerSettings } from '../../src/eval/g2-reranker-profile.ts';
import { candidateKeys, evidenceStages, feasibleEvidence } from '../../src/eval/trace_v2.ts';
import { observeRecall, recall } from '../../src/retrieval/qmd-integration.ts';

function document(key, page, text, { project = 'fixture', start = 1, end = 1, revision = 'current' } = {}) {
  const span = { kind: 'page', object: page, revision, start, end };
  const passage = {
    kind: 'current-page', page, revision, start, end, text, hash: 'whole-body-hash', title: 'A "quoted" title',
    snapshot: { authority: 'synthetic', project, epoch: 'epoch', sequence: 2 },
    citation: { kind: 'page', page, revision, start, end, hash: 'whole-body-hash' },
  };
  return { key, span, passage, bytes: Buffer.byteLength(JSON.stringify(passage)) };
}

test('the oracle uses full JSON byte costs and requires exact project-scoped evidence', () => {
  const first = document('a', 'A', 'Café "quoted"\nsecond line');
  const second = document('b', 'B', 'Українська');
  const lookalike = document('c', 'B', 'Українська', { project: 'other' });
  const pageOnly = document('d', 'B', 'additional details');
  const facts = [{ page: 'A', span: 'Café "quoted"\nsecond' }, { page: 'B', span: 'Українська' }];
  const baseBytes = 110;
  const cap = baseBytes + first.bytes + second.bytes + 1;
  const whole = feasibleEvidence([first, second, lookalike, pageOnly], 'fixture', facts, { baseBytes, cap, passageLimit: 10 });
  assert.equal(whole.status, 'proved');
  assert.equal(whole.matched, 2);
  assert.equal(whole.bytes, cap);
  assert.deepEqual(new Set(whole.witness.map(p => p.key)), new Set(['a', 'b']));
  assert.equal(feasibleEvidence([first, second], 'fixture', facts, { baseBytes, cap: cap - 1, passageLimit: 10 }).matched, 1);
  assert.equal(feasibleEvidence([first, lookalike, pageOnly], 'fixture', facts, { baseBytes, cap, passageLimit: 10 }).matched, 1);
  assert.equal(feasibleEvidence([pageOnly], 'fixture', [{ page: 'B', span: null }], { baseBytes, cap, passageLimit: 10 }).matched, 1);
  assert.equal(feasibleEvidence([first, second], 'fixture', facts, { baseBytes, cap, passageLimit: 1 }).matched, 1);
  assert.equal(feasibleEvidence([first, second], 'fixture', facts, { baseBytes, cap, passageLimit: 10 }, 0).status, 'unknown');
});

test('the oracle explores compatible alternatives and shares recall overlap semantics', () => {
  const overlap = document('overlap', 'A', 'first', { start: 2, end: 5 });
  const alternative = document('alternative', 'A', 'a much longer first', { start: 1, end: 1 });
  const second = document('second', 'A', 'second', { start: 5, end: 5 });
  const facts = [{ page: 'A', span: 'first' }, { page: 'A', span: 'second' }];
  const packing = { baseBytes: 100, cap: 24000, passageLimit: 10 };
  assert.equal(feasibleEvidence([overlap, second], 'fixture', facts, packing).matched, 1);
  const best = feasibleEvidence([overlap, second, alternative], 'fixture', facts, packing);
  assert.equal(best.matched, 2);
  assert.deepEqual(best.witness.map(p => p.key).sort(), ['alternative', 'second']);
});

test('actual recall exposes ordered overflow and exact packing without affecting returned context', async t => {
  const directory = mkdtempSync(join(tmpdir(), 'wiki-g2-trace-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const database = join(directory, 'authority.db');
  execFileSync('python3', ['-c', `
import sys
sys.path.insert(0, "src/authority")
from authority import connect_knowledge
store = connect_knowledge(sys.argv[1], "fixture")
for n in range(14):
    store.create_page("fixture", f"fixture-{n}", f"Fixture {n}", 'Some \\n fixture café "quoted" evidence.', "owner")
`, database]);
  const binding = { database, project: 'fixture', indexRoot: directory };
  const input = { query: 'fixture' };
  const unobserved = await recall(binding, input);
  const calls = [];
  observeRecall({ stage() {}, lists(lists) { calls.push(lists); } });
  try {
    const observed = await recall(binding, input);
    assert.deepEqual(observed, unobserved);
    const [trace] = calls;
    assert.equal(trace.rerankAdmission, 'disabled');
    assert.equal(trace.reranked, false);
    assert.equal(trace.emitted.length, 10);
    assert.equal(trace.skippedForPassageLimit.length, 4);
    assert.deepEqual(trace.ordered, [...trace.emitted, ...trace.skippedForPassageLimit]);
    const totals = new Map(trace.documents.map(doc => [doc.key, doc.bytes]));
    assert.equal(trace.baseBytes + trace.emitted.reduce((sum, key) => sum + totals.get(key), 0) + 9,
      Buffer.byteLength(JSON.stringify(observed)));
    for (const [index, key] of trace.emitted.entries()) {
      const doc = trace.documents.find(candidate => candidate.key === key);
      assert.deepEqual(doc.passage, observed.evidence.passages[index]);
    }
    assert.equal(evidenceStages(new Set([trace.emitted[0]]), trace, candidateKeys(trace)).loss, 'emitted');
    assert.equal(evidenceStages(new Set([trace.skippedForPassageLimit[0]]), trace, candidateKeys(trace)).loss, 'passage-limit');
    assert.equal(evidenceStages(new Set(['absent']), trace, candidateKeys(trace)).loss, 'not-retrieved');
    const bounded = await recall(binding, { ...input, maxBytes: 2048 });
    const limited = calls[1];
    assert.ok(limited.skippedForBytes.length > 0);
    assert.equal(evidenceStages(new Set([limited.skippedForBytes[0]]), limited, candidateKeys(limited)).loss, 'byte-cap');
    assert.ok(Buffer.byteLength(JSON.stringify(bounded)) <= limited.cap);
  } finally {
    observeRecall(undefined);
  }
});

test('clause-only and exact hits contribute to the ceiling independently of rerank admission', () => {
  const trace = {
    lexical: [], exact: ['exact'], vector: ['primary'], clauseVectors: [['winner', 'clause-alternative']],
    clauseWinners: ['winner'], expansionCandidates: ['expansion'], fused: ['primary'], head: ['primary'],
    rerankAdmission: 'busy', reranked: false, rerankOrder: ['primary'], ranked: ['exact', 'winner', 'primary'],
    direct: ['exact', 'winner', 'primary'], expanded: ['expansion'], ordered: ['exact', 'winner', 'primary', 'expansion'],
    emitted: ['exact', 'winner', 'primary', 'expansion'], skippedForOverlap: [], skippedForBytes: [], skippedForPassageLimit: [],
  };
  const union = candidateKeys(trace);
  assert.deepEqual([...union], ['exact', 'primary', 'winner', 'clause-alternative', 'expansion']);
  assert.equal(evidenceStages(new Set(['exact']), trace, union).loss, 'emitted');
  const missed = evidenceStages(new Set(['clause-alternative']), trace, union);
  assert.deepEqual(missed.clauses, [['clause-alternative']]);
  assert.deepEqual(missed.rerankHead, []);
  assert.equal(missed.loss, 'not-selected');
});

test('the frozen profile rejects overrides while performance development accepts them', t => {
  const keys = ['WIKI_EVAL_RERANK_DEVICE', 'WIKI_EVAL_RERANK_DEPTH', 'WIKI_EVAL_RERANK_TOKENS'];
  const previous = keys.map(key => process.env[key]);
  t.after(() => keys.forEach((key, i) => {
    if (previous[i] === undefined) delete process.env[key];
    else process.env[key] = previous[i];
  }));
  keys.forEach(key => delete process.env[key]);
  assert.deepEqual(evaluationRerankerSettings(), { device: 'vulkan', depth: 24, docTokens: 512 });
  process.env.WIKI_EVAL_RERANK_DEVICE = 'cpu';
  process.env.WIKI_EVAL_RERANK_DEPTH = '30';
  process.env.WIKI_EVAL_RERANK_TOKENS = '256';
  assert.throws(() => evaluationRerankerSettings(), /overrides differ/);
  assert.deepEqual(evaluationRerankerSettings(true), { device: 'cpu', depth: 30, docTokens: 256 });
  process.env.WIKI_EVAL_RERANK_DEPTH = '65';
  assert.throws(() => evaluationRerankerSettings(true), /invalid G2 reranker settings/);
});
