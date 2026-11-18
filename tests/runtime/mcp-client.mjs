// Real official-SDK stdio client used by isolated protocol tests and host probes.
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
const root = fileURLToPath(new URL('../../', import.meta.url));
let input = '';
for await (const chunk of process.stdin) input += chunk;
const request = JSON.parse(input);
const client = new Client({name: 'wiki-runtime-test', version: '1.0.0'});
const transport = new StdioClientTransport({command: process.execPath,
  args: [resolve(root, 'node_modules/tsx/dist/cli.mjs'), resolve(root, 'src/mcp/stdio.ts'),
    request.database, request.project, request.principal ?? 'worker'],
  env: {...(request.indexRoot ? {WIKI_INDEX_ROOT:request.indexRoot} : {}),
        ...(request.model ? {WIKI_QMD_MODEL:request.model} : {})}, stderr: 'pipe'});
let stderr = '';
transport.stderr?.on('data', chunk => {stderr += chunk.toString();});
try {
  await client.connect(transport);
  const tools = await client.listTools();
  const results = [];
  for (const call of request.calls ?? []) {
    try { results.push(await client.callTool(call)); }
    catch (error) { results.push({isError:true, protocolError:String(error)}); }
  }
  console.log(JSON.stringify({tools:tools.tools, results}));
} catch (error) {
  console.log(JSON.stringify({error:String(error), stderr}));
  process.exitCode = 1;
} finally { await client.close(); }
