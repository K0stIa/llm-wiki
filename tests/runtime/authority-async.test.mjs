import assert from 'node:assert/strict';
import {test} from 'node:test';
import {BoundedJsonRpc} from '../../src/retrieval/async-authority.ts';
const command=(ms,value=1)=>[process.execPath,'-e',`setTimeout(()=>process.stdout.write(JSON.stringify(${JSON.stringify(value)})),${ms})`];
test('async RPC yields event loop, limits four children and bounds pending admission',async()=>{
 const pool=new BoundedJsonRpc({maxActive:4,maxPending:2,deadlineMs:1000,maxBuffer:1024});
 let tick=false;setTimeout(()=>tick=true,5);
 const jobs=Array.from({length:6},()=>pool.run(command(80),{}));
 await assert.rejects(pool.run(command(0),{}),/capacity/);
 assert.equal(pool.activeCount,4);assert.equal(pool.pendingCount,2);
 await new Promise(r=>setTimeout(r,20));assert.equal(tick,true);
 assert.deepEqual(await Promise.all(jobs),[1,1,1,1,1,1]);assert.equal(pool.activeCount,0);assert.equal(pool.pendingCount,0);
});
test('deadline includes queue wait and cleanup precedes rejection',async()=>{
 const pool=new BoundedJsonRpc({maxActive:1,maxPending:2,deadlineMs:80,maxBuffer:1024});
 const a=pool.run(command(1000),{});const b=pool.run(command(1000),{});
 const r=await Promise.allSettled([a,b]);assert.ok(r.every(x=>x.status==='rejected'&&/deadline/.test(x.reason.message)));
 assert.equal(pool.activeCount,0);assert.equal(pool.pendingCount,0);
 assert.equal(await pool.run(command(0,7),{}),7);
});
test('overflow, malformed JSON, nonzero exit, missing binary and input serialization fail closed',async()=>{
 const pool=new BoundedJsonRpc({maxActive:2,maxPending:4,deadlineMs:1000,maxBuffer:128});
 for(const argv of [[process.execPath,'-e',`process.stdout.write('x'.repeat(1000))`],[process.execPath,'-e',`process.stdout.write('bad')`],[process.execPath,'-e','process.exit(3)'],['/nonexistent/wiki-command']]) await assert.rejects(pool.run(argv,{}));
 const cycle={};cycle.self=cycle;await assert.rejects(pool.run(command(0),cycle));
 await assert.rejects(pool.run(command(0),'x'.repeat(300)),/input/);
 assert.equal(pool.activeCount,0);assert.equal(pool.pendingCount,0);assert.equal(await pool.run(command(0,8),{}),8);
});
test('queued payload bytes are bounded independently of job count',async()=>{
 const pool=new BoundedJsonRpc({maxActive:1,maxPending:10,deadlineMs:1000,maxBuffer:128});
 const running=pool.run(command(50),{});const queued=pool.run(command(0),'x'.repeat(80));
 await assert.rejects(pool.run(command(0),'x'.repeat(80)),/capacity/);
 await Promise.all([running,queued]);assert.equal(pool.activeCount,0);assert.equal(pool.pendingCount,0);
});
