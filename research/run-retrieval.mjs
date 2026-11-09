import assert from 'node:assert/strict';
import { mkdirSync, readFileSync, writeFileSync, rmSync, copyFileSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';
import { performance } from 'node:perf_hooks';
import { fixture, root, work, results, wikiLib, wikiPackage, qmdPackage, piPackage, sha256, version } from './lib.mjs';

const { getVaultPaths } = await wikiLib('utils');
const { bootstrapVault } = await wikiLib('bootstrap');
const { createKnowledgeDocument, writeKnowledgeDocumentFile } = await wikiLib('knowledge-document');
const { rebuildMetadata } = await wikiLib('metadata');
const { searchWiki } = await wikiLib('recall');
const { createStore } = await import(pathToFileURL(join(qmdPackage, 'dist/index.js')));
const challenge = process.argv.includes('--challenge');
const suite = challenge ? JSON.parse(readFileSync(join(root, 'research/challenge.json'), 'utf8')) : fixture;
const workspace = challenge ? join(work, 'challenge') : work;
mkdirSync(workspace, { recursive: true });
const vaultRoot = join(workspace, 'zosma');
const common = join(workspace, 'corpus');
const nvkRoot = join(workspace, 'nvk');
for (const dir of [vaultRoot, common, nvkRoot]) {
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
}
const paths = getVaultPaths(vaultRoot);
assert.equal(bootstrapVault(paths, { topic: fixture.name, mode: 'personal' }).ok, true);
const index = ['# Synthetic comparison wiki', '', 'These are invented facts for a benchmark. Read exact pages before answering.', ''];
for (const doc of fixture.documents) {
  const target = join(paths.wiki, `${doc.id}.md`);
  mkdirSync(dirname(target), { recursive: true });
  const knowledge = createKnowledgeDocument(`${doc.id}.md`, {
    type: 'concept', title: doc.title, created: '2026-01-01', updated: doc.updated || '2026-02-20',
    status: doc.status || 'current', description: doc.summary,
  }, doc.body);
  writeKnowledgeDocumentFile(target, knowledge);
  for (const base of [common, join(nvkRoot, '.wiki/wiki')]) {
    const copy = join(base, `${doc.id}.md`);
    mkdirSync(dirname(copy), { recursive: true });
    copyFileSync(target, copy);
  }
  index.push(`- [${doc.title}](wiki/${doc.id}.md): ${doc.summary}`);
}
mkdirSync(join(nvkRoot, '.wiki'), { recursive: true });
writeFileSync(join(nvkRoot, '.wiki/_index.md'), index.join('\n') + '\n');
writeFileSync(join(nvkRoot, '.wiki/wiki/_index.md'), index.join('\n').replaceAll('(wiki/', '(') + '\n');
assert.equal(rebuildMetadata(paths).ok, true);
const registry = JSON.parse(readFileSync(join(paths.meta, 'registry.json'), 'utf8'));
for (const d of fixture.documents) assert.ok(registry.pages[d.id], `Missing page ${d.id}`);

const dbPath = join(workspace, 'qmd.sqlite');
for (const suffix of ['', '-wal', '-shm']) rmSync(dbPath + suffix, { force: true });
const store = await createStore({ dbPath, config: { collections: { corpus: { path: common, pattern: '**/*.md' } } } });
const start = performance.now();
const updated = await store.update();
const indexingMs = performance.now() - start;
const records = [];
try {
  for (const query of suite.queries) {
    let t = performance.now();
    const z = searchWiki(paths, query.query, 5);
    records.push({ engine: 'zosma-lexical', query: query.id, ids: z.map(r => r.id), scores: z.map(r => r.score), elapsed_ms: performance.now() - t });
    t = performance.now();
    const q = await store.searchLex(query.query, { limit: 5, collection: 'corpus' });
    records.push({ engine: 'qmd-bm25', query: query.id, ids: q.map(r => {
      const value = r.filepath || r.file || r.displayPath;
      assert.equal(typeof value, 'string');
      return value.replace(/^qmd:\/\/corpus\//, '').replace(/\.md$/, '');
    }), scores: q.map(r => r.score), elapsed_ms: performance.now() - t });
  }
} finally { await store.close(); }
const payload = {
  corpus: fixture.name, fixture_sha256: sha256(readFileSync(join(root, 'research/fixture.json'))),
  documents: fixture.documents.length, queries: suite.queries.length,
  suite: suite.name, challenge_sha256: challenge ? sha256(readFileSync(join(root, 'research/challenge.json'))) : null,
  versions: { zosma: version(wikiPackage), qmd: version(qmdPackage), pi: version(piPackage), node: process.version },
  source_hashes: Object.fromEntries(['recall', 'metadata', 'retro'].map(name => [name, sha256(readFileSync(join(wikiPackage, `extensions/llm-wiki/lib/${name}.ts`)))])),
  nvk_commit: execFileSync('git', ['-C', join(root, '.cache/upstreams/nvk'), 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(),
  qmd_indexing: { ...updated, elapsed_ms: indexingMs },
  limitations: ['QMD searchLex uses AND semantics. Natural-language failures are not hybrid-search results.', 'No embeddings or reranking models downloaded.', 'One pass per retrieval mode; timings exclude package startup and model download and are not a throughput benchmark.', 'nvk query-lite is evaluated separately as an agent workflow.'],
  records,
};
const output = join(results, challenge ? 'challenge-retrieval.json' : 'retrieval.json');
writeFileSync(output, JSON.stringify(payload, null, 2) + '\n');
console.log(JSON.stringify({ documents: payload.documents, queries: payload.queries, indexing_ms: indexingMs, results: relative(root, output) }));
