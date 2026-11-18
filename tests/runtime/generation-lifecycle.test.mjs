import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import * as qmd from '@tobilu/qmd';
import { setDefaultLlamaCpp } from '../../node_modules/@tobilu/qmd/dist/llm.js';
import { acquireGeneration, generationRoot, stageGenerationIndex } from '../../src/retrieval/qmd-integration.ts';
import { digest, APPROVED_MODEL_SHA256 } from '../../src/retrieval/offline.ts';
function fixture(t) {
  const directory = mkdtempSync(join(tmpdir(), 'wiki-pin-lifecycle-'));
  t.after(() => rmSync(directory, {recursive:true, force:true}));
  const binding = {database:join(directory,'authority.db'),project:'synthetic',indexRoot:directory};
  const root = generationRoot(binding), generation = `g-${randomUUID()}`;
  mkdirSync(join(root,generation), {recursive:true});
  const database = Buffer.from('synthetic immutable fixture, never opened by QMD');
  writeFileSync(join(root,generation,'index.sqlite'), database);
  writeFileSync(join(root,generation,'manifest.json'), JSON.stringify({version:1,qmdVersion:'2.8.3',generation,
    target:{authority:'test',project:'synthetic',epoch:'epoch',sequence:0},modelDigest:APPROVED_MODEL_SHA256,
    databaseDigest:digest(database),chunkLines:32,documents:[],outboxIds:[]}));
  writeFileSync(join(root,'current'),generation);
  return {binding,leases:join(root,'leases',generation)};
}
test('release closes admission immediately, before lease removal completes', async t => {
  const {binding,leases} = fixture(t);
  const pin = await acquireGeneration(binding);
  const closing = pin.release();
  try { await assert.rejects(pin.search('synthetic'), /generation reader is closed/); }
  finally { await closing; }
  assert.deepEqual(readdirSync(leases), []);
});
test('idempotent release cleans lease after a rejected search', async t => {
  const {binding,leases} = fixture(t);
  const pin = await acquireGeneration(binding);
  const search = assert.rejects(pin.search('synthetic'), /cached embedding unavailable/);
  const firstRelease = pin.release(), secondRelease = pin.release();
  assert.equal(firstRelease, secondRelease);
  await Promise.all([search,firstRelease,secondRelease]);
  assert.deepEqual(readdirSync(leases), []);
  await assert.rejects(pin.search('synthetic'), /generation reader is closed/);
});

test('a staged generation reuses live embeddings and removes superseded chunks', async t => {
  const work = mkdtempSync(join(tmpdir(), 'wiki-incremental-index-'));
  t.after(() => rmSync(work, { recursive: true, force: true }));
  // Keep the real QMD indexing, embedding bookkeeping, maintenance, and search.
  // Replace only the local model's tokenizer and numeric inference.
  setDefaultLlamaCpp({ tokenize: async text => Array.from(text) });
  t.after(() => setDefaultLlamaCpp(null));
  const embedded = [];
  const result = { embedding: [1, 0, 0, 0] };
  const sdk = {
    ...qmd,
    async createStore(options) {
      const store = await qmd.createStore(options);
      store.internal.llm.embed = async () => result;
      store.internal.llm.embedBatch = async texts => {
        embedded.push(...texts);
        return texts.map(() => result);
      };
      return store;
    },
  };
  const binding = { project: 'synthetic', indexRoot: work };
  const root = generationRoot(binding);
  const generation = `g-${randomUUID()}`;
  const original = join(root, generation);
  const model = 'test-embeddinggemma.gguf';
  const chunk = (object, revision, text) => ({
    kind: 'page', object, revision, text, start: 1, end: 1, hash: digest(text), title: object,
    key: digest(`${object}:${revision}`),
  });
  const stable = chunk('Stable', 'r1', 'Stable vector should be reused.');
  const republished = chunk('Stable', 'r2', stable.text);
  const old = chunk('Changing', 'r1', 'Obsolete vector must be removed.');
  const retired = chunk('Retired', 'r1', 'Retired vector must be removed.');
  const revised = chunk('Changing', 'r2', 'Replacement requires a fresh vector.');
  const target = { authority: 'test', project: binding.project, epoch: 'epoch', sequence: 1 };
  const documents = [stable, old, retired];
  await stageGenerationIndex(binding, { snapshot: target, documents }, original, model, sdk);
  const originalDb = readFileSync(join(original, 'index.sqlite'));
  writeFileSync(join(original, 'manifest.json'), JSON.stringify({
    version: 1, qmdVersion: '2.8.3', generation, target, modelDigest: APPROVED_MODEL_SHA256,
    databaseDigest: digest(originalDb), chunkLines: 32, documents, outboxIds: [],
  }));
  writeFileSync(join(root, 'current'), generation);

  embedded.length = 0;
  const staging = join(root, 'next');
  const snapshot = { ...target, sequence: 2 };
  await stageGenerationIndex(binding, { snapshot, documents: [republished, revised] }, staging, model, sdk);
  assert.equal(embedded.length, 1);
  assert.match(embedded[0], /Replacement requires a fresh vector/);
  assert.deepEqual(readFileSync(join(original, 'index.sqlite')), originalDb);
  assert.deepEqual(readdirSync(join(root, 'leases', generation)), []);

  const next = await sdk.createStore({ dbPath: join(staging, 'index.sqlite') });
  try {
    const paths = (await next.searchVector('query', { collection: 'corpus' })).map(doc => doc.filepath).sort();
    assert.deepEqual(paths, [republished, revised].map(doc => `qmd://corpus/${doc.key}.md`).sort());
    const cleanup = new qmd.Maintenance(next.internal).preview();
    assert.equal(cleanup.orphanedVectors, 0);
    assert.equal(cleanup.inactiveDocs, 0);
  } finally { await next.close(); }

  embedded.length = 0;
  await stageGenerationIndex(binding, {
    snapshot: { ...snapshot, epoch: 'restored' }, documents: [stable, revised],
  }, join(root, 'restored'), model, sdk);
  assert.equal(embedded.length, 2);

  embedded.length = 0;
  await stageGenerationIndex(binding, { snapshot, documents }, join(root, 'alternate-model'),
    '/alternate/test-embeddinggemma.gguf', sdk);
  assert.equal(embedded.length, 3);
});
