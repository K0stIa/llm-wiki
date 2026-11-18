#!/usr/bin/env node
/** Bounded, local-only P2 measurement. No private text is emitted in the report. */
import { readFileSync, mkdtempSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import { performance } from "node:perf_hooks";
import * as z from "zod/v4";
import { buildGeneration, recall, authorityRpc, closeQmdReaders } from "./qmd-integration.js";
import { digest } from "./offline.js";
const [model, output] = process.argv.slice(2);
if (!model || !output) throw new Error("Usage: tsx measure-hybrid.ts APPROVED_CACHED_MODEL OUTPUT_JSON");
const root = fileURLToPath(new URL("../../", import.meta.url));
const frozen = join(root, "research/eval-corpus/frozen/v1");
const docs = z.array(z.object({ id:z.string(), body:z.string(), project:z.string(), slice_type:z.string() })).parse(JSON.parse(readFileSync(join(frozen,"documents.json"),"utf8")));
const questions = z.array(z.object({ id:z.string(), query:z.string(), gold_pages:z.array(z.string()), is_positive:z.boolean() })).parse(JSON.parse(readFileSync(join(frozen,"questions.json"),"utf8")));
const byId = new Map(docs.map(d => [d.id,d]));
const work = mkdtempSync(join(tmpdir(),"wiki-hybrid-measure-"));
const database = join(work,"authority.db");
execFileSync("python3",["-c",`import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1])/'src/authority'))
from authority import connect_knowledge
docs=json.loads((Path(sys.argv[1])/'research/eval-corpus/frozen/v1/documents.json').read_text())
stores={}
for d in docs:
 if d['project'] not in stores: stores[d['project']]=connect_knowledge(sys.argv[2],d['project'])
 stores[d['project']].create_page(d['project'],d['id'],d['title'],d['body'],'local-evaluator')
`,root,database],{timeout:60000,stdio:["ignore","ignore","pipe"]});
const projects = [...new Set(docs.map(d=>d.project))];
for (const project of projects) await buildGeneration({database,project,indexRoot:join(work,"indexes"),model});
const groups = new Map<string, typeof questions>();
for (const q of questions) {
  const doc = byId.get(q.gold_pages[0] ?? "");
  if (!doc) throw new Error("unresolved gold");
  const group = groups.get(doc.slice_type) ?? [];
  group.push(q); groups.set(doc.slice_type,group);
}
const sample = [...groups.values()].flatMap(group=>group.sort((a,b)=>digest(a.id).localeCompare(digest(b.id))).slice(0,4));
const records = [];
let exact = 0, citations = 0, maxBytes = 0;
for (const q of sample) {
  const doc = byId.get(q.gold_pages[0] ?? "");
  if (!doc) throw new Error("unresolved gold");
  const binding = {database,project:doc.project,indexRoot:join(work,"indexes"),model};
  const start = performance.now();
  const result = await recall(binding,{query:q.query,coverage:"require-hybrid-current"});
  if (!("coverage" in result) || result.coverage !== "hybrid-current" || !("evidence" in result)) throw new Error("measurement did not execute current hybrid");
  const parsed = z.array(z.object({page:z.string(),revision:z.string(),start:z.number(),end:z.number(),hash:z.string(),text:z.string()})).parse(result.evidence.passages);
  maxBytes = Math.max(maxBytes,Buffer.byteLength(JSON.stringify(result)));
  for (const p of parsed) {
    const raw = authorityRpc(binding,"wiki_page",{page:p.page,revision:p.revision});
    const page = z.object({hash:z.string(),markdown:z.string()}).parse(raw);
    citations++;
    exact += Number(page.hash === p.hash && page.markdown.split("\n").slice(p.start-1,p.end).join("\n") === p.text);
  }
  const found = new Set(parsed.map(p=>p.page));
  records.push({id_sha256:digest(q.id),slice:doc.slice_type,positive:q.is_positive,
    recall:q.gold_pages.filter(p=>found.has(p)).length/q.gold_pages.length,
    all_gold:q.gold_pages.every(p=>found.has(p)),seconds:(performance.now()-start)/1000});
  writeFileSync(resolve(output),JSON.stringify({status:"RUNNING",completed:records.length,total:sample.length}));
}
const positives = records.filter(r=>r.positive);
const report = {status:"MEASURED_HYBRID_NOT_FULL_G2",qmdVersion:"2.8.3",model_sha256:digest(readFileSync(model)),
  sample:"four SHA256(id)-ordered questions per slice, not a pre-frozen holdout",total:records.length,positive:positives.length,
  recall_at_10:positives.reduce((n,r)=>n+r.recall,0)/positives.length,
  all_gold_at_10:positives.filter(r=>r.all_gold).length/positives.length,
  exact_citation_resolution:exact/citations,citations,max_compact_json_bytes:maxBytes,
  p95_seconds:records.map(r=>r.seconds).sort((a,b)=>a-b)[Math.ceil(records.length*.95)-1],
  peak_rss_bytes:process.resourceUsage().maxRSS*1024,
  corpus_sha256:Object.fromEntries(["questions.json","documents.json","split.json","manifest.json"].map(f=>[f,digest(readFileSync(join(frozen,f)))])),
  implementation_sha256:Object.fromEntries(["src/retrieval/qmd-integration.ts","src/retrieval/offline.ts","src/authority/authority.py",
    "src/authority/retrieval.py","src/authority/migrations.sql","src/mcp/authority_rpc.py"].map(f=>[f,digest(readFileSync(join(root,f)))])),
  limitations:["No semantic answer correctness or abstention measurement.","Single-project, single-gold-page v1 corpus does not prove adversarial scope, genuine multi-page completeness or supersession behavior.","Readers retain one warm private SDK copy per process; cold startup and resource hash verification are included in latency.","Approved cached research weights only; no production model-license approval is claimed."],records};
writeFileSync(resolve(output),JSON.stringify(report,null,2));
await closeQmdReaders();
