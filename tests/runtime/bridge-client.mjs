import * as bridge from '../../src/authority/bridge.ts';
import {backup, restore, createWikiService} from '../../src/mcp/transport.ts';
let input='';
for await (const part of process.stdin) input+=part;
const request=JSON.parse(input);
try {
  const results=[];
  for (const call of request.calls) {
    if(call.tool==='backup') results.push(backup(bridge.connect(...call.args.slice(0,2)),call.args[2]));
    else if(call.tool==='restore') results.push(restore(...call.args));
    else if(call.tool==='service') results.push(await createWikiService(...call.binding).callTool(call.name,call.args));
    else results.push(await bridge[call.tool](...call.args));
  }
  process.stdout.write(JSON.stringify({results}));
} catch(error) { process.stdout.write(JSON.stringify({exception:String(error)})); }
