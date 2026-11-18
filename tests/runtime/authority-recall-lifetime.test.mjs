import assert from 'node:assert/strict';
import {test} from 'node:test';
import cp from 'node:child_process';
import {syncBuiltinESMExports} from 'node:module';
import {mkdtempSync,mkdirSync,writeFileSync,readdirSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {recall,generationRoot,compoundQueryParts,protectFront} from '../../src/retrieval/qmd-integration.ts';
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
