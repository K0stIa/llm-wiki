import assert from 'node:assert/strict';
import {test} from 'node:test';
import cp from 'node:child_process';
import {registerHooks,syncBuiltinESMExports} from 'node:module';
import {mkdtempSync,mkdirSync,writeFileSync,readdirSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {acquireGeneration,closeQmdReaders,observeRecall,recall,generationRoot,compoundQueryParts,protectFront} from '../../src/retrieval/qmd-integration.ts';
import {digest,APPROVED_MODEL_SHA256} from '../../src/retrieval/offline.ts';

test('only independent question clauses reserve distinct passages after protected results', () => {
  assert.deepEqual(compoundQueryParts('Where is the service configured and how do I restart it?'),
    ['Where is the service configured', 'how do I restart it?']);
  assert.deepEqual(compoundQueryParts('How do I run backup and recovery for the project?'), []);
  assert.deepEqual(compoundQueryParts('Who owns it and why now?'), []);
  assert.deepEqual(compoundQueryParts('What is the default and where is it read and how do I override it?'), []);
  const objects = { exact: 'i', first: 'a', second: 'b', duplicate: 'a', third: 'c', other: 'd' };
  assert.deepEqual(protectFront(['other', 'third', 'first', 'second', 'duplicate'], ['exact'],
    ['first', 'second', 'other'], 2, key => objects[key], ['duplicate', 'unverified', 'third']),
    ['exact', 'first', 'second', 'third', 'other', 'duplicate']);
});
test('recall pins before async snapshot, retains captured authority/epoch and releases after every RPC outcome',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'wiki-async-recall-'));const original=cp.execFile;
 const binding={database:join(dir,'authority.sqlite'),project:'synthetic',indexRoot:dir};const root=generationRoot(binding),generation=`g-${randomUUID()}`;
 mkdirSync(join(root,generation),{recursive:true});const bytes=Buffer.from('synthetic never opened by QMD');
 const target={authority:'captured-authority',project:'synthetic',epoch:'captured-epoch',sequence:7};
 writeFileSync(join(root,generation,'index.sqlite'),bytes);writeFileSync(join(root,'current'),generation);
 writeFileSync(join(root,generation,'manifest.json'),JSON.stringify({version:1,qmdVersion:'2.8.3',generation,target,modelDigest:APPROVED_MODEL_SHA256,databaseDigest:digest(bytes),chunkLines:32,documents:[],outboxIds:[]}));
 const leases=join(root,'leases',generation);
 try {
  for(const fail of [undefined,'wiki_recall_snapshot','wiki_recall_resolve']) {
   const calls=[];
   cp.execFile=(file,args,options,callback)=>{
    assert.equal(file,'python3');assert.equal(readdirSync(leases).length,1);const tool=args.at(-1);calls.push(tool);
    const value=tool==='wiki_recall_snapshot'?{snapshot:target,documents:[],lexical:[],links:{},sourceLinks:{},chunkLines:32,outboxIds:[]}:[];
    const script=`let s='';process.stdin.on('data',c=>s+=c);process.stdin.on('end',()=>{const a=JSON.parse(s);if(${JSON.stringify(tool)}==='wiki_recall_resolve'&&(a.authority!=='captured-authority'||a.epoch!=='captured-epoch'))process.exit(9);setTimeout(()=>{${tool===fail?'process.exit(4)':'process.stdout.write('+JSON.stringify(JSON.stringify(value))+')'}},10);});`;
    return original(process.execPath,['-e',script],options,callback);
   };syncBuiltinESMExports();
   if(fail) await assert.rejects(recall(binding,{query:'fixture'}));
   else {const result=await recall(binding,{query:'fixture'});assert.deepEqual(result.snapshot,target);}
   assert.deepEqual(readdirSync(leases),[]);
   assert.deepEqual(calls,fail==='wiki_recall_snapshot'?['wiki_recall_snapshot']:['wiki_recall_snapshot','wiki_recall_resolve']);
  }
 } finally {cp.execFile=original;syncBuiltinESMExports();rmSync(dir,{recursive:true,force:true});}
});

test('recall resolves only the complete passages that fit and rejects an altered resolver response', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'wiki-recall-bounded-'));
  const original = cp.execFile;
  const binding = { database: join(dir, 'authority.sqlite'), project: 'synthetic', indexRoot: dir };
  const target = { authority: 'test', project: 'synthetic', epoch: 'test', sequence: 1 };
  const documents = Array.from({ length: 14 }, (_, index) => ({
    kind: 'page', object: `page-${index}`, revision: `revision-${index}`, start: 1, end: 1,
    hash: `h:${digest(String(index))}`, title: 'Fixture', text: index === 0 ? 'λ'.repeat(1200) : 'citable text',
    key: digest(`key-${index}`),
  }));
  const snapshot = { snapshot: target, documents, lexical: documents.map(doc => doc.key), exact: [],
    links: {}, sourceLinks: {}, chunkLines: 32, outboxIds: [] };
  let altered = false;
  try {
    cp.execFile = (file, args, options, callback) => {
      let script;
      if (args.at(-1) === 'wiki_recall_snapshot') {
        script = `process.stdin.resume();process.stdin.on('end',()=>process.stdout.write(${JSON.stringify(JSON.stringify(snapshot))}));`;
      } else {
        script = `let input='';process.stdin.on('data',d=>input+=d);process.stdin.on('end',()=>{const refs=JSON.parse(input).passages;if(!refs.length||refs.length>=10||refs[0].object!=='page-1')process.exit(7);if(${altered})refs[0].text='altered';process.stdout.write(JSON.stringify(refs));});`;
      }
      return original(process.execPath, ['-e', script], options, callback);
    };
    syncBuiltinESMExports();
    const result = await recall(binding, { query: 'fixture', maxBytes: 2048 });
    const pages = result.evidence.passages.map(p => p.page);
    assert.ok(pages.length > 1 && pages.length < 10);
    assert.deepEqual(pages, Array.from({ length: pages.length }, (_, index) => `page-${index + 1}`));
    assert.ok(Buffer.byteLength(JSON.stringify(result)) <= 2048);
    altered = true;
    await assert.rejects(recall(binding, { query: 'fixture', maxBytes: 2048 }), /resolved passage differs/);
  } finally {
    cp.execFile = original;
    syncBuiltinESMExports();
    rmSync(dir, { recursive: true, force: true });
  }
});

test('native recall measures cold and warm dispatch, failing verification and expiry', async t => {
  const dir = mkdtempSync(join(tmpdir(), 'wiki-native-timing-'));
  const binding = { database: join(dir, 'authority.sqlite'), project: 'fixture', indexRoot: dir,
    model: join(dir, 'synthetic.gguf') };
  const root = generationRoot(binding), generation = `g-${randomUUID()}`;
  const index = join(root, generation, 'index.sqlite');
  const target = { authority: 'fixture', project: 'fixture', epoch: 'fixture', sequence: 1 };
  const doc = { kind: 'page', object: 'fixture', revision: 'revision', start: 1, end: 1,
    hash: `h:${digest('fixture evidence')}`, title: 'Fixture', text: 'fixture evidence', key: digest('key') };
  const snapshot = { snapshot: target, documents: [doc], lexical: [doc.key],
    links: {}, sourceLinks: {}, chunkLines: 32, outboxIds: [] };
  mkdirSync(join(root, generation), { recursive: true });
  writeFileSync(index, 'synthetic index');
  writeFileSync(binding.model, 'synthetic model');
  writeFileSync(join(root, 'current'), generation);
  writeFileSync(join(root, generation, 'manifest.json'), JSON.stringify({
    version: 1, qmdVersion: '2.8.3', generation, target, modelDigest: APPROVED_MODEL_SHA256,
    databaseDigest: digest('synthetic index'), chunkLines: 32, documents: [doc], outboxIds: [],
  }));

  const original = cp.execFile;
  let hashes = 0, opens = 0, searches = 0, approved = true;
  let holdDigest;
  let failOpen = false;
  const mockKey = Symbol.for('wiki.syntheticQmd');
  globalThis[mockKey] = async () => {
    opens++;
    if (failOpen) throw new Error('synthetic reader failure');
    return { close: async () => {}, searchVector: async () => {
      searches++;
      return [{ filepath: `qmd://corpus/${doc.key}.md`, score: 1 }];
    } };
  };
  const mock = 'data:text/javascript,export const createStore = globalThis[Symbol.for("wiki.syntheticQmd")]';
  const hooks = registerHooks({ resolve(specifier, context, next) {
    return specifier === '@tobilu/qmd' ? { url: mock, shortCircuit: true } : next(specifier, context);
  } });
  cp.execFile = (file, args, options, callback) => {
    if (file === '/usr/bin/sha256sum') {
      hashes++;
      const finish = () => callback(null, `${approved ? APPROVED_MODEL_SHA256 : digest('wrong')}  fixture\0`);
      if (holdDigest) holdDigest(finish);
      else queueMicrotask(finish);
      return;
    }
    const output = args.at(-1) === 'wiki_recall_snapshot'
      ? `process.stdout.write(${JSON.stringify(JSON.stringify(snapshot))})`
      : 'process.stdout.write(JSON.stringify(JSON.parse(input).passages))';
    return original(process.execPath, ['-e', `let input='';
      process.stdin.on('data',data=>input+=data);process.stdin.on('end',()=>{${output}})`], options, callback);
  };
  syncBuiltinESMExports();
  t.after(async () => {
    observeRecall(undefined);
    await closeQmdReaders();
    cp.execFile = original;
    syncBuiltinESMExports();
    hooks.deregister();
    delete globalThis[mockKey];
    rmSync(dir, { recursive: true, force: true });
  });

  const names = [];
  const input = { query: 'fixture', coverage: 'require-hybrid-current' };
  observeRecall({ stage(name, ms) {
    assert.ok(Number.isFinite(ms) && ms >= 0);
    if (name.startsWith('vector.')) names.push(name);
  } });
  const cold = await recall(binding, input);
  assert.deepEqual(names.splice(0), ['vector.queue', 'vector.model-verify', 'vector.reader-setup', 'vector.search']);
  assert.equal(cold.evidence.passages[0].citation.hash, doc.hash);
  assert.deepEqual(await recall(binding, input), cold);
  assert.deepEqual(names.splice(0), ['vector.queue', 'vector.model-verify', 'vector.reader-setup', 'vector.search']);
  assert.deepEqual([hashes, opens, searches], [2, 1, 2]);

  const pin = await acquireGeneration(binding);
  try {
    assert.deepEqual(await pin.searchPlan({ primary: 'fixture', supplemental: [], deadlineMs: performance.now() }),
      { kind: 'primary-unavailable', reason: 'deadline' });
    assert.deepEqual(names, []);
  } finally { await pin.release(); }

  approved = false;
  assert.equal((await recall(binding, input)).reason, 'model-or-vector-unavailable');
  assert.deepEqual(names.splice(0), ['vector.queue', 'vector.model-verify']);
  assert.deepEqual([hashes, opens, searches], [3, 1, 2]);

  writeFileSync(index, 'corrupt index');
  assert.equal((await recall(binding, input)).reason, 'generation-integrity');
  assert.deepEqual(names, []);
  assert.equal(hashes, 3);

  writeFileSync(index, 'synthetic index');
  approved = true;
  observeRecall(undefined);
  assert.deepEqual(await recall(binding, input), cold);

  observeRecall({ stage(name, ms) {
    if (name.startsWith('vector.')) names.push([name, ms]);
  } });
  const activePin = await acquireGeneration(binding);
  const waitingPin = await acquireGeneration(binding);
  const leases = join(root, 'leases', generation);
  let now = 100;
  const clock = t.mock.method(performance, 'now', () => now);
  const plan = { primary: 'fixture', supplemental: [], deadlineMs: 100_100 };
  const started = new Promise(resolve => { holdDigest = resolve; });
  const active = activePin.searchPlan(plan);
  const finish = await started;
  const waiting = waitingPin.searchPlan(plan);
  const release = activePin.release();
  try {
    assert.equal(hashes, 5);
    assert.equal(readdirSync(leases).length, 2);
    assert.deepEqual(names, [['vector.queue', 0]]);
    now = plan.deadlineMs;
  } finally {
    finish();
    holdDigest = undefined;
  }
  try {
    const expired = { kind: 'primary-unavailable', reason: 'deadline' };
    assert.deepEqual(await active, expired);
    assert.deepEqual(await waiting, expired);
    await release;
    assert.equal(readdirSync(leases).length, 1);
    assert.deepEqual(names, [
      ['vector.queue', 0], ['vector.model-verify', 100_000], ['vector.reader-setup', 0],
    ]);
    assert.deepEqual([hashes, opens, searches], [5, 1, 3]);
  } finally {
    clock.mock.restore();
    await waitingPin.release();
  }

  names.length = 0;
  await closeQmdReaders();
  failOpen = true;
  assert.equal((await recall(binding, input)).reason, 'model-or-vector-unavailable');
  assert.deepEqual(names.map(([name]) => name), ['vector.queue', 'vector.model-verify', 'vector.reader-setup']);
  assert.deepEqual([hashes, opens, searches], [6, 2, 3]);
});
