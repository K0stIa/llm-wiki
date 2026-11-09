import assert from 'node:assert/strict';
import { fork, execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { work, results, root, wikiLib, wikiPackage, version, sha256 } from './lib.mjs';

const { getVaultPaths } = await wikiLib('utils');
const { bootstrapVault } = await wikiLib('bootstrap');
const { rebuildMetadata } = await wikiLib('metadata');
const { captureText } = await wikiLib('source-packet');
const outcomes = [];
for (const mode of ['distinct-pages', 'same-page', 'capture']) {
  const directory = join(work, `concurrency-${mode}`);
  rmSync(directory, { recursive: true, force: true });
  mkdirSync(directory, { recursive: true });
  const paths = getVaultPaths(directory);
  assert.equal(bootstrapVault(paths, { topic: 'Synthetic concurrency', mode: 'personal' }).ok, true);
  const count = mode === 'capture' ? 12 : mode === 'same-page' ? 1 : 8;
  const concurrency = 8;
  const workers = [];
  const messages = [];
  const ready = [];
  const exits = [];
  for (let i = 0; i < concurrency; i++) {
    const child = fork(fileURLToPath(new URL('./write-worker.mjs', import.meta.url)), [directory, mode, String(i), String(count)], { stdio: ['ignore', 'ignore', 'pipe', 'ipc'] });
    workers.push(child);
    child.stderr.on('data', b => messages.push({ error: b.toString() }));
    ready.push(new Promise((resolve, reject) => {
      let announced = false;
      child.on('message', message => { if (message.ready) { announced = true; resolve(); } else messages.push(message); });
      child.once('error', reject);
      child.once('exit', code => { if (!announced) reject(new Error(`Worker exited before ready: ${code}`)); });
    }));
    exits.push(new Promise(resolve => child.once('exit', code => resolve(code))));
  }
  const timer = setTimeout(() => workers.forEach(c => c.kill('SIGKILL')), 45000);
  let registryReads = 0, invalidRegistryReads = 0;
  const reader = setInterval(() => {
    registryReads++;
    try { JSON.parse(readFileSync(join(paths.meta, 'registry.json'), 'utf8')); }
    catch { invalidRegistryReads++; }
  }, 1);
  let exitCodes;
  try {
    await Promise.all(ready);
    workers.forEach(c => c.send({ start: true }));
    exitCodes = await Promise.all(exits);
  } catch (error) {
    workers.forEach(child => child.kill('SIGKILL'));
    throw error;
  } finally { clearTimeout(timer); clearInterval(reader); }
  const writes = messages.flatMap(m => m.writes || []);
  const before = JSON.parse(readFileSync(join(paths.meta, 'registry.json'), 'utf8'));
  const rebuild = rebuildMetadata(paths);
  const after = JSON.parse(readFileSync(join(paths.meta, 'registry.json'), 'utf8'));
  const events = readFileSync(join(paths.meta, 'events.jsonl'), 'utf8').trim().split('\n').map(l => JSON.parse(l));
  const expected = concurrency * count;
  let survivingMarkers;
  if (mode === 'capture') {
    const raw = readdirSync(paths.rawSources).map(id => readFileSync(join(paths.rawSources, id, 'extracted.md'), 'utf8')).join('\n');
    survivingMarkers = writes.filter(w => raw.includes(`Synthetic raw marker ${w.marker}\n`)).length;
  } else {
    const pages = readdirSync(join(paths.wiki, 'sources')).map(p => readFileSync(join(paths.wiki, 'sources', p), 'utf8')).join('\n');
    survivingMarkers = writes.filter(w => pages.includes(`Synthetic concurrent insight ${w.marker}\n`)).length;
  }
  outcomes.push({ mode, processes: concurrency, requested_writes: expected, acknowledged_writes: writes.length,
    unique_ids: new Set(writes.map(w => w.id)).size, surviving_markers: survivingMarkers,
    registry_reads: registryReads, invalid_registry_reads: invalidRegistryReads,
    registry_pages_before_reconciliation: Object.keys(before.pages).length,
    registry_pages_after_reconciliation: Object.keys(after.pages).length,
    events_for_writes: events.filter(e => ['capture', 'retro'].includes(e.kind)).length,
    reconciliation_ok: rebuild.ok, exit_codes: exitCodes,
    worker_errors: messages.filter(m => m.error).map(m => m.error),
  });
}
const nvk = execFileSync('bash', [join(root, '.cache/upstreams/nvk/tests/test-session-concurrency.sh')], { encoding: 'utf8', timeout: 90000 }).replace(/\x1b\[[0-9;]*m/g, '');
const directory = join(work, 'concurrency-single-writer-control');
rmSync(directory, { recursive: true, force: true });
mkdirSync(directory, { recursive: true });
const controlPaths = getVaultPaths(directory);
assert.equal(bootstrapVault(controlPaths, { topic: 'Single writer control', mode: 'personal' }).ok, true);
const controlIds = [];
for (let n = 0; n < 96; n++) controlIds.push(captureText(controlPaths, `Synthetic raw marker writer-control-entry-${n}\n` + 'padding '.repeat(1000), `writer-control-entry-${n}`).sourceId);
const report = {
  versions: { zosma: version(wikiPackage), node: process.version },
  source_hashes: Object.fromEntries(['utils', 'source-packet', 'retro', 'metadata'].map(name => [name, sha256(readFileSync(join(wikiPackage, `extensions/llm-wiki/lib/${name}.ts`)))])),
  single_writer_control: { requested_writes: 96, unique_ids: new Set(controlIds).size, source_packets: readdirSync(controlPaths.rawSources).length },
  zosma: outcomes, nvk_upstream_session_regression: nvk.trim(),
  limitations: ['One finite stress run per scenario, not a proof of safety.', 'nvk test covers its session-hook state, not simultaneous edits to compiled wiki pages.', 'Atomic per-file metadata replacement is not a multi-file transaction or a page merge policy.'] };
writeFileSync(join(results, 'concurrency.json'), JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify(report, null, 2));
