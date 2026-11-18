import assert from 'node:assert/strict';
import { PassThrough, Writable } from 'node:stream';
import { test } from 'node:test';
import { ProtocolStdioServerTransport as Transport } from '../../src/mcp/protocol-stdio.ts';
test('MCP response stays on original output when dependency redirects write', async () => {
  const output = new PassThrough();
  let received = '', redirected = '';
  output.on('data', b => { received += b; });
  const transport = new Transport(new PassThrough(), output);
  output.write = chunk => { redirected += chunk; return true; };
  await transport.send({jsonrpc:'2.0',id:53,result:{ok:true}});
  assert.equal(redirected, '');
  assert.equal(JSON.parse(received).id, 53);
});

test('send waits for buffered output completion', async () => {
  let release;
  const output = new Writable({highWaterMark:1, write(chunk, enc, callback) { release = callback; }});
  const transport = new Transport(new PassThrough(), output);
  let done = false;
  const sent = transport.send({jsonrpc:'2.0',id:1,result:{}}).then(() => { done = true; });
  await Promise.resolve();
  assert.equal(done, false);
  release(); await sent;
  assert.equal(done, true);
  await transport.close();
});
test('failed output rejects send and reports stream error', async () => {
  const failure = new Error('output failed');
  const output = new Writable({write(chunk, enc, callback) { callback(failure); }});
  const transport = new Transport(new PassThrough(), output);
  let observed;
  transport.onerror = error => { observed = error; };
  await assert.rejects(transport.send({jsonrpc:'2.0',id:2,result:{}}), /output failed/);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(observed, failure);
  await transport.close();
});
test('actual QMD redirect keeps native noise on stderr and MCP on stdout', async () => {
  const { spawnSync } = await import('node:child_process');
  const code = `
    import { ProtocolStdioServerTransport } from './src/mcp/protocol-stdio.ts';
    import { withNativeStdoutRedirectedToStderr } from './node_modules/@tobilu/qmd/dist/llm.js';
    const transport = new ProtocolStdioServerTransport();
    await withNativeStdoutRedirectedToStderr(async () => {
      process.stdout.write('native-noise\\n');
      await transport.send({jsonrpc:'2.0',id:54,result:{ok:true}});
    });
    await transport.close();
  `;
  const run = spawnSync(process.execPath, ['--import','tsx','--input-type','module','-e',code], {
    cwd: new URL('../../', import.meta.url), encoding:'utf8', timeout:10000,
  });
  assert.equal(run.status, 0, run.stderr);
  assert.equal(JSON.parse(run.stdout).id, 54);
  assert.match(run.stderr, /native-noise/);
  assert.doesNotMatch(run.stderr, /jsonrpc/);
});
test('close drains pending write failure safely and rejects later sends', async () => {
  let release;
  const output = new Writable({write(chunk, enc, callback) { release = callback; }});
  const transport = new Transport(new PassThrough(), output);
  const sent = transport.send({jsonrpc:'2.0',id:3,result:{}});
  const rejected = assert.rejects(sent, /late failure/);
  const closing = transport.close();
  release(new Error('late failure'));
  await rejected;
  await closing;
  await assert.rejects(transport.send({jsonrpc:'2.0',id:4,result:{}}), /closed/);
});
