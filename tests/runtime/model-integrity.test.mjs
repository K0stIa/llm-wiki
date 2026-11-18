import assert from 'node:assert/strict';
import { test } from 'node:test';
import fs from 'node:fs';
import { syncBuiltinESMExports } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { checkedModel, fileDigest, digest } from '../../src/retrieval/offline.ts';
test('model integrity reads in bounded chunks and checks content on every call', t => {
  const dir = fs.mkdtempSync(join(tmpdir(),'wiki-integrity-'));
  t.after(() => fs.rmSync(dir,{recursive:true,force:true}));
  const path = join(dir,'synthetic.gguf');
  fs.writeFileSync(path, Buffer.alloc(256*1024, 1));
  const originalWhole = fs.readFileSync, originalRead = fs.readSync;
  let bytes = 0, largest = 0;
  fs.readFileSync = (p, ...args) => { if(p === path) throw new Error('unbounded model read'); return originalWhole(p,...args); };
  fs.readSync = (fd, buffer, ...args) => { largest=Math.max(largest, buffer.byteLength); const n=originalRead(fd,buffer,...args); bytes+=n; return n; };
  syncBuiltinESMExports();
  try {
    assert.throws(() => checkedModel(path), /unapproved cached embedding hash/);
    assert.equal(bytes,256*1024);
    fs.writeFileSync(path, Buffer.alloc(256*1024, 2));
    assert.throws(() => checkedModel(path), /unapproved cached embedding hash/);
    assert.equal(bytes,512*1024);
    assert.ok(largest <= 64*1024);
  } finally { fs.readFileSync=originalWhole; fs.readSync=originalRead; syncBuiltinESMExports(); }
});

test('streamed digest equals byte digest including partial final chunk', t => {
  const dir = fs.mkdtempSync(join(tmpdir(),'wiki-hash-'));
  t.after(() => fs.rmSync(dir,{recursive:true,force:true}));
  const path = join(dir,'fixture');
  for (const size of [0,1,65535,65536,65537,196625]) {
    const content = Buffer.alloc(size, 123);
    fs.writeFileSync(path,content);
    assert.equal(fileDigest(path),digest(content));
  }
});
test('read failure propagates and closes opened descriptor', t => {
  const dir = fs.mkdtempSync(join(tmpdir(),'wiki-hash-error-'));
  t.after(() => fs.rmSync(dir,{recursive:true,force:true}));
  const path = join(dir,'fixture'); fs.writeFileSync(path,'test');
  const originalRead=fs.readSync, originalClose=fs.closeSync;
  let closed=0;
  fs.readSync=() => { throw new Error('injected read failure'); };
  fs.closeSync=fd => { closed++; return originalClose(fd); };
  syncBuiltinESMExports();
  try { assert.throws(() => fileDigest(path), /injected read failure/); assert.equal(closed,1); }
  finally {fs.readSync=originalRead;fs.closeSync=originalClose;syncBuiltinESMExports();}
});

test('async model digest yields to event loop and checks every invocation', async t => {
  const module = await import('../../src/retrieval/offline.ts');
  assert.equal(typeof module.fileDigestAsync, 'function');
  const dir=fs.mkdtempSync(join(tmpdir(),'wiki-async-hash-'));
  t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
  const path=join(dir,'file with spaces\\and\nnewline');
  fs.writeFileSync(path,Buffer.alloc(4*1024*1024,7));
  const expected=fileDigest(path);
  let completed=false;
  const hash=module.fileDigestAsync(path).then(value=>{completed=true;return value;});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(completed,false,'digest must not block the event loop');
  assert.equal(await hash,expected);
  fs.writeFileSync(path,Buffer.alloc(4*1024*1024,8));
  assert.notEqual(await module.fileDigestAsync(path),expected);
  await assert.rejects(module.fileDigestAsync(join(dir,'missing')));
  const results=await Promise.all(Array.from({length:12},()=>module.fileDigestAsync(path)));
  assert.ok(results.every(value=>value===fileDigest(path)));
});

test('parallel full hashes are bounded to four real child processes', async t => {
  const module=await import('../../src/retrieval/offline.ts');
  const cp=(await import('node:child_process')).default;
  const directory=fs.mkdtempSync(join(tmpdir(),'wiki-hash-concurrency-'));
  t.after(()=>fs.rmSync(directory,{recursive:true,force:true}));
  const path=join(directory,'unapproved.gguf');fs.writeFileSync(path,Buffer.alloc(4*1024*1024,9));
  const original=cp.execFile;let active=0,peak=0;
  cp.execFile=(file,args,options,callback)=>{
    active++;peak=Math.max(peak,active);
    return original(file,args,options,(...result)=>{active--;callback(...result);});
  };
  syncBuiltinESMExports();
  try {
    const replies=await Promise.allSettled(Array.from({length:12},(_,i)=>module.fileDigestAsync(i===5?join(directory,'missing'):path)));
    assert.equal(replies.filter(r=>r.status==='rejected').length,1);
    assert.equal(active,0);assert.equal(peak,4);
    await assert.rejects(module.offlineQmd(path,join(directory,'cache')),/unapproved cached embedding hash/);
    assert.equal(active,0);
  } finally {cp.execFile=original;syncBuiltinESMExports();}
});
