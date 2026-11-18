// Actual adapter driver. Multiple commands retain real generation leases.
import { createInterface } from 'node:readline';
import { buildGeneration, recall, acquireGeneration, cleanupGenerations, authorityRpc, fuseRanks, applyRerank, orderByScores, protectFront, tryRerankLock, closeQmdReaders } from '../../src/retrieval/qmd-integration.ts';
const pins = new Map();
let heldLock;
for await (const line of createInterface({input:process.stdin})) {
  try {
    const r = JSON.parse(line);
    let value;
    switch (r.action) {
      case 'build': value = await buildGeneration(r.binding); break;
      case 'recall': value = await recall(r.binding, r.input); break;
      case 'legacyRecall': {
        process.env.WIKI_INDEX_ROOT = r.binding.indexRoot;
        process.env.WIKI_QMD_MODEL = r.binding.model;
        const {createMCPServer} = await import('../../src/mcp/transport.ts');
        value = await createMCPServer(r.binding.database,r.binding.project).handler('wiki_recall',r.input);
        break;
      }
      case 'snapshot': value = authorityRpc(r.binding,'wiki_recall_snapshot',{query:r.query??''}); break;
      case 'pin': {
        const pin = await acquireGeneration(r.binding);
        if (!pin) throw new Error('no generation');
        pins.set(r.id,pin); value = {manifest:pin.manifest,directory:pin.directory}; break;
      }
      case 'search': value = await pins.get(r.id).search(r.query); break;
      case 'release': await pins.get(r.id).release(); value = true; break;
      case 'cleanup': value = await cleanupGenerations(r.binding); break;
      case 'fuse': value = fuseRanks(r.lexical,r.vector); break;
      case 'rerankMerge': value = applyRerank(r.ranked,r.head,r.order); break;
      case 'protect': value = protectFront(r.ranked,r.exact,r.fused,r.n,key=>r.objects[key]); break;
      case 'scores': value = orderByScores(r.keys,r.scores); break;
      case 'setEnv': process.env[r.name] = r.value; value = true; break;
      case 'lockTry': { const release = await tryRerankLock(r.path); if (release) heldLock = release; value = Boolean(release); break; }
      case 'lockRelease': await heldLock?.(); heldLock = undefined; value = true; break;
      case 'crash': process.exit(19);
      default: throw new Error('unknown test action');
    }
    console.log(JSON.stringify({ok:true,value}));
  } catch(error) { console.log(JSON.stringify({ok:false,error:String(error)})); }
}
for (const pin of pins.values()) await pin.release();
await closeQmdReaders();
