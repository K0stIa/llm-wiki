// QMD vector and explicit lex+vec fusion. No generation/reranker model is used.
import { readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { performance } from 'node:perf_hooks';
import { fixture, root, work, results, qmdPackage, sha256 } from './lib.mjs';
process.env.XDG_CACHE_HOME = join(work, 'model-cache');
process.env.QMD_FORCE_CPU = '1';
const { createStore } = await import(pathToFileURL(join(qmdPackage, 'dist/index.js')));
const { DEFAULT_EMBED_MODEL_URI } = await import(pathToFileURL(join(qmdPackage, 'dist/llm.js')));
const store = await createStore({ dbPath: join(work, 'qmd.sqlite') });
const start = performance.now();
let embedded;
try {
  embedded = await store.embed({ force: true, maxDocsPerBatch: 24 });
  const embeddingMs = performance.now() - start;
  const suites = [
    { filename: 'retrieval.json', queries: fixture.queries },
    { filename: 'challenge-retrieval.json', queries: JSON.parse(readFileSync(join(root, 'research/challenge.json'), 'utf8')).queries },
  ];
  for (const suite of suites) {
    const path = join(results, suite.filename);
    const report = JSON.parse(readFileSync(path, 'utf8'));
    report.records = report.records.filter(r => !['qmd-vector', 'qmd-lex-vector-fusion'].includes(r.engine));
    for (const query of suite.queries) {
      for (const engine of ['qmd-vector', 'qmd-lex-vector-fusion']) {
        const t = performance.now();
        const hits = engine === 'qmd-vector'
          ? await store.searchVector(query.query, { limit: 5, collection: 'corpus' })
          : await store.search({ queries: [{ type: 'lex', query: query.query }, { type: 'vec', query: query.query }], rerank: false, limit: 5, collection: 'corpus' });
        const ids = hits.map(r => (r.filepath || r.file || r.displayPath).replace(/^qmd:\/\/corpus\//, '').replace(/\.md$/, ''));
        report.records.push({ engine, query: query.id, ids, scores: hits.map(r => r.score), elapsed_ms: performance.now() - t });
      }
    }
    const models = readdirSync(join(process.env.XDG_CACHE_HOME, 'qmd/models')).filter(n => n.endsWith('.gguf'));
    report.vector_configuration = {
      embedding_model: DEFAULT_EMBED_MODEL_URI, cpu_only: true, embedding_ms: embeddingMs,
      embed_result: embedded,
      model_sha256: Object.fromEntries(models.map(n => [n, sha256(readFileSync(join(process.env.XDG_CACHE_HOME, 'qmd/models', n)))])),
      expansion: 'disabled by explicit lex and vec queries', reranking: false,
      limitation: 'Vector and RRF results have no tuned abstention threshold. Inspect negative-query false positives.',
    };
    report.limitations = report.limitations.filter(x => x !== 'No embeddings or reranking models downloaded.');
    report.limitations.push('One isolated 334 MB embedding model was downloaded. No generation/reranking model was downloaded.');
    writeFileSync(path, JSON.stringify(report, null, 2) + '\n');
  }
  console.log(JSON.stringify({ embedded, embedding_seconds: (performance.now() - start) / 1000, suites: suites.length }));
} finally { await store.close(); }
