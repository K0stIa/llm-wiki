import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { syncBuiltinESMExports } from 'node:module';
import fsPromises from 'node:fs/promises';
import { test } from 'node:test';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, renameSync, chmodSync, existsSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import * as qmd from '@tobilu/qmd';
import { setDefaultLlamaCpp } from '../../node_modules/@tobilu/qmd/dist/llm.js';
import { acquireGeneration, cleanupGenerations, copyGenerationSnapshot, generationRoot, stageGenerationIndex } from '../../src/retrieval/qmd-integration.ts';
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
  return {binding,root,generation,leases:join(root,'leases',generation)};
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

test('evaluation snapshots copy only verified generation artifacts', async t => {
  const {binding,root,generation,leases} = fixture(t);
  const source = join(root, generation);
  const files = ['index.sqlite', 'manifest.json'];
  const original = files.map(file => readFileSync(join(source, file)));
  const pointer = readFileSync(join(root, 'current'));
  writeFileSync(join(source, 'unrelated'), 'exclude this');
  const destination = {...binding, indexRoot: join(binding.indexRoot, 'snapshot')};
  await copyGenerationSnapshot(binding, destination);
  const copied = generationRoot(destination);
  assert.deepEqual(readdirSync(join(copied, generation)).sort(), files);
  assert.deepEqual(files.map(file => readFileSync(join(copied, generation, file))), original);
  const pin = await acquireGeneration(destination);
  await pin.release();
  assert.deepEqual(readdirSync(leases), []);

  const conflict = {...destination, indexRoot: join(binding.indexRoot, 'conflict')};
  mkdirSync(join(generationRoot(conflict), 'current'), {recursive:true});
  await assert.rejects(copyGenerationSnapshot(binding, conflict), /EEXIST/);
  assert.deepEqual(readdirSync(generationRoot(conflict)), ['current']);
  assert.deepEqual(readdirSync(leases), []);
  assert.deepEqual(files.map(file => readFileSync(join(source, file))), original);
  assert.deepEqual(readFileSync(join(root, 'current')), pointer);
});

test('evaluation snapshots refuse malformed generation artifacts', async t => {
  const {binding,root,generation} = fixture(t);
  const destination = {...binding, indexRoot: join(binding.indexRoot, 'snapshot')};
  for (const [path, value] of [
    [join(root, 'current'), '../invalid'],
    [join(root, generation, 'manifest.json'), '{}'],
    [join(root, generation, 'index.sqlite'), 'wrong digest'],
  ]) {
    const bytes = readFileSync(path);
    writeFileSync(path, value);
    await assert.rejects(copyGenerationSnapshot(binding, destination));
    writeFileSync(path, bytes);
  }
});

test('a source that denies lease creation fails before copying', {skip: process.getuid?.() === 0}, async t => {
  const {binding, root, generation} = fixture(t);
  const destination = {...binding, indexRoot: join(binding.indexRoot, 'snapshot')};
  await (await acquireGeneration(binding)).release();
  const leases = join(root, 'leases', generation);
  const pointer = readFileSync(join(root, 'current'));
  const index = readFileSync(join(root, generation, 'index.sqlite'));
  chmodSync(leases, 0o500);
  try {
    await assert.rejects(copyGenerationSnapshot(binding, destination), /grant write access.*source index root/);
  } finally {
    chmodSync(leases, 0o700);
  }
  assert.equal(existsSync(generationRoot(destination)), false);
  assert.deepEqual(readdirSync(leases), []);
  assert.deepEqual(readFileSync(join(root, 'current')), pointer);
  assert.deepEqual(readFileSync(join(root, generation, 'index.sqlite')), index);
});

test('the source survives concurrent cleanup during a failing copy', async t => {
  const {binding,root,generation,leases} = fixture(t);
  const current = join(root, 'current');
  const pointer = readFileSync(current);
  const index = join(root, generation, 'index.sqlite');
  const bytes = readFileSync(index);
  const destination = {...binding, indexRoot: join(binding.indexRoot, 'snapshot')};
  t.mock.method(fsPromises, 'copyFile', async () => {
    assert.equal(readdirSync(leases).length, 1);
    writeFileSync(current, `g-${randomUUID()}`);
    try {
      assert.deepEqual(await cleanupGenerations(binding), []);
      assert.deepEqual(readFileSync(index), bytes);
    } finally {
      writeFileSync(current, pointer);
    }
    throw new Error('simulated copy failure');
  });
  syncBuiltinESMExports();
  try {
    await assert.rejects(copyGenerationSnapshot(binding, destination), /simulated copy failure/);
  } finally {
    t.mock.restoreAll();
    syncBuiltinESMExports();
  }
  assert.deepEqual(readdirSync(leases), []);
  assert.deepEqual(readdirSync(generationRoot(destination)), []);
  assert.deepEqual(readFileSync(index), bytes);
  assert.deepEqual(readFileSync(current), pointer);
});

test('trace reuse backs up the authority and invokes the leased snapshot copy', t => {
  const {binding,root,generation} = fixture(t);
  const source = binding.indexRoot;
  // Place the fixture under the indexes directory used by the trace entry point.
  const indexRoot = join(source, 'indexes');
  mkdirSync(indexRoot);
  const savedRoot = generationRoot({...binding, indexRoot});
  renameSync(root, savedRoot);
  const python = '.venv/bin/python';
  execFileSync(python, ['-B', '-c', `
import sqlite3, sys
with sqlite3.connect(sys.argv[1]) as db:
    db.execute("CREATE TABLE fixture (value)")
    db.execute("INSERT INTO fixture VALUES (42)")
`, binding.database], {timeout: 20_000});
  writeFileSync(join(source, 'trace-provenance.json'), JSON.stringify({
    subset: 'development', manifest_sha256: 'fixture',
    identity: {model: {sha256: APPROVED_MODEL_SHA256}},
  }));
  const second = generationRoot({indexRoot, project: 'second'});
  mkdirSync(join(second, generation), {recursive: true});
  writeFileSync(join(second, 'current'), generation);
  const manifest = JSON.parse(readFileSync(join(savedRoot, generation, 'manifest.json')));
  manifest.target.project = 'second';
  writeFileSync(join(second, generation, 'manifest.json'), JSON.stringify(manifest));
  writeFileSync(join(second, generation, 'index.sqlite'), readFileSync(join(savedRoot, generation, 'index.sqlite')));
  const output = join(source, 'trace');
  mkdirSync(output);
  const trace = ['-B', '-c', `
import sqlite3, sys
from pathlib import Path
from src.eval.trace_v2 import reuse_generation
source, destination = map(Path, sys.argv[1:3])
reuse_generation(source, destination, {'synthetic', 'second'}, 'fixture', sys.argv[3])
with sqlite3.connect(destination / 'authority.db') as db:
    assert db.execute('SELECT value FROM fixture').fetchone() == (42,)
`];
  execFileSync(python, [...trace, source, output, APPROVED_MODEL_SHA256], {timeout: 20_000});
  const copied = generationRoot({...binding, indexRoot: join(output, 'indexes')});
  assert.equal(readFileSync(join(copied, 'current'), 'utf8').trim(), generation);
  assert.deepEqual(readFileSync(join(copied, generation, 'index.sqlite')),
    readFileSync(join(savedRoot, generation, 'index.sqlite')));
  assert.deepEqual(readdirSync(join(savedRoot, 'leases', generation)), []);
  const copiedSecond = generationRoot({indexRoot: join(output, 'indexes'), project: 'second'});
  assert.equal(readFileSync(join(copiedSecond, 'current'), 'utf8').trim(), generation);
  assert.deepEqual(readdirSync(join(second, 'leases', generation)), []);

  const otherDigest = digest('alternate expected model');
  const mismatchOutput = join(source, 'trace-mismatch');
  mkdirSync(mismatchOutput);
  writeFileSync(join(source, 'trace-provenance.json'), JSON.stringify({
    subset: 'development', manifest_sha256: 'fixture',
    identity: {model: {sha256: otherDigest}},
  }));
  const mismatch = spawnSync(python, [...trace, source, mismatchOutput, otherDigest],
    {encoding: 'utf8', timeout: 20_000});
  assert.ifError(mismatch.error);
  assert.equal(mismatch.status, 1);
  assert.match(mismatch.stderr, /source generation model digest does not match the expected digest/);
  assert.equal(existsSync(join(mismatchOutput, 'indexes')), false);
  assert.deepEqual(readdirSync(join(second, 'leases', generation)), []);
});

test('the performance runner rejects malformed and unleasable generations before timing recall', t => {
  const {binding, root, generation} = fixture(t);
  const source = binding.indexRoot;
  const rankings = JSON.stringify({buildSeconds: 0});
  const report = JSON.stringify({subset: 'development', raw_rankings_sha256: digest(rankings)});
  const commit = execFileSync('git', ['rev-parse', 'HEAD'], {encoding: 'utf8', timeout: 5000}).trim();
  writeFileSync(join(source, 'retrieval-run.json'), JSON.stringify({
    report_sha256: digest(report), identity: {commit, dirty: true},
  }));
  writeFileSync(join(source, 'report.json'), report);
  writeFileSync(join(source, 'raw.json'), rankings);
  writeFileSync(join(source, 'questions.json'), JSON.stringify(Array.from({length: 110},
    (_, id) => ({id: String(id), query: 'synthetic', project: 'main'}))));
  execFileSync('.venv/bin/python', ['-B', '-c', `
import sqlite3, sys
with sqlite3.connect(sys.argv[1]) as db:
    db.execute("CREATE TABLE page_heads (project)")
`, binding.database], {timeout: 20_000});
  const indexRoot = join(source, 'indexes');
  const original = generationRoot({indexRoot, project: 'main'});
  mkdirSync(original, {recursive: true});
  writeFileSync(join(original, 'current'), '../invalid');
  const model = join(source, 'synthetic-model');
  writeFileSync(model, 'synthetic bytes');
  const output = join(source, 'perf');
  const result = spawnSync(process.execPath, ['--import', 'tsx', 'src/eval/perf_v2.ts',
    source, output, model, model, '--development'], {encoding: 'utf8', timeout: 20_000});
  assert.ifError(result.error);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /invalid generation pointer/);
  assert.equal(result.stdout, '');
  assert.deepEqual(readdirSync(output), ['authority.db']);

  renameSync(join(root, generation), join(original, generation));
  const manifestPath = join(original, generation, 'manifest.json');
  const manifest = JSON.parse(readFileSync(manifestPath));
  manifest.target.project = 'main';
  writeFileSync(manifestPath, JSON.stringify(manifest));
  writeFileSync(join(original, 'current'), generation);
  rmSync(join(original, '.lock'));
  mkdirSync(join(original, '.lock'));
  const deniedOutput = join(source, 'perf-denied');
  const denied = spawnSync(process.execPath, ['--import', 'tsx', 'src/eval/perf_v2.ts',
    source, deniedOutput, model, model, '--development'], {encoding: 'utf8', timeout: 20_000});
  assert.ifError(denied.error);
  assert.equal(denied.status, 1);
  assert.match(denied.stderr, /grant write access.*source index root/);
  assert.equal(denied.stdout, '');
  assert.deepEqual(readdirSync(deniedOutput), ['authority.db']);
});
