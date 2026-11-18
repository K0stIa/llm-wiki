#!/usr/bin/env node
/**
 * Ten-reader warm recall latency on the committed synthetic v1 corpus (no private text).
 * 10 readers x 10 queries, one authority write overlapping the run. Reranking is on when WIKI_RERANK_MODEL is set.
 *
 *   tsx src/eval/perf_readers.ts MODEL OUT_JSON shared|processes
 *
 * shared:    one process serves all ten readers concurrently (one MCP service owner).
 * processes: ten processes, one reader each (exercises the machine-wide reranker admission lock).
 * stdout and OUT_JSON carry numbers and hashes only.
 */
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { execFileSync, spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { performance } from "node:perf_hooks";
import { buildGeneration, recall, closeQmdReaders, rerankerFromEnv, type Binding } from "../retrieval/qmd-integration.js";

type Row = { reader: number; step: number; seconds: number; degradation: string | null; bytes: number };
const sha = (s: string) => createHash("sha256").update(s).digest("hex");
const root = fileURLToPath(new URL("../../", import.meta.url));

async function lane(binding: Binding, reader: number, queries: string[], onDone: () => void): Promise<Row[]> {
  const rows: Row[] = [];
  for (const [step, query] of queries.entries()) {
    const start = performance.now();
    const result = await recall({ ...binding, reranker: rerankerFromEnv() }, { query, coverage: "best-available" });
    if (result.kind !== "context") throw new Error(`recall returned ${result.kind}`);
    rows.push({ reader, step, seconds: (performance.now() - start) / 1000,
      degradation: "degradation" in result ? String(result.degradation) : null, bytes: Buffer.byteLength(JSON.stringify(result)) });
    onDone();
  }
  return rows;
}

if (process.argv[2] === "--worker") {
  const { binding, reader, queries } = JSON.parse(process.argv[3]);
  const rows = await lane(binding, reader, queries, () => process.stdout.write("done\n"));
  process.stdout.write("ROWS " + JSON.stringify(rows) + "\n");
  await closeQmdReaders();
  process.exit(0);
}

const [model, out, mode] = process.argv.slice(2);
if (!model || !out || (mode !== "shared" && mode !== "processes")) throw new Error("usage: perf_readers.ts MODEL OUT_JSON shared|processes");
const frozen = join(root, "research/eval-corpus/frozen/v1");
const questions: { id: string; query: string }[] = JSON.parse(readFileSync(join(frozen, "questions.json"), "utf8"));
const work = mkdtempSync(join(tmpdir(), "wiki-perf-readers-"));
const database = join(work, "authority.db");
const seed = `import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1])/'src/authority'))
from authority import connect_knowledge
docs=json.loads((Path(sys.argv[1])/'research/eval-corpus/frozen/v1/documents.json').read_text())
s=connect_knowledge(sys.argv[2],docs[0]['project'])
for d in docs: s.create_page(d['project'],d['id'],d['title'],d['body'],'local-evaluator')
print(docs[0]['project'])`;
const project = execFileSync("python3", ["-c", seed, root, database], { encoding: "utf8" }).trim();
const binding: Binding = { database, project, indexRoot: join(work, "indexes"), model };
await buildGeneration(binding);
await closeQmdReaders();
const sample = questions.slice().sort((a, b) => sha(a.id).localeCompare(sha(b.id))).slice(0, 100).map(q => q.query);
const plan = Array.from({ length: 10 }, (_, r) => sample.slice(r * 10, r * 10 + 10));
const writer = `import sys
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1])/'src/authority'))
from authority import connect_knowledge
connect_knowledge(sys.argv[2],sys.argv[3]).create_page(sys.argv[3],'perf-overlap-write','Overlap write','Synthetic overlap write PERF-OVERLAP-1.','local-evaluator')`;
let completed = 0, wrote: Promise<void> | undefined, writeWindow: [number, number] | undefined;
const progress = () => {
  if (++completed === 10 && !wrote) wrote = (async () => {
    const start = performance.now();
    execFileSync("python3", ["-c", writer, root, database, project]);
    writeWindow = [start, performance.now()];
  })();
};
const windowStart = performance.now();
let rows: Row[];
if (mode === "shared") {
  rows = (await Promise.all(plan.map((queries, reader) => lane(binding, reader, queries, progress)))).flat();
} else {
  rows = (await Promise.all(plan.map((queries, reader) => new Promise<Row[]>((resolve, reject) => {
    const child = spawn(process.execPath, ["--import", "tsx", fileURLToPath(import.meta.url), "--worker", JSON.stringify({ binding, reader, queries })],
      { cwd: root, env: process.env, stdio: ["ignore", "pipe", "inherit"] });
    let buffer = "", result: Row[] | undefined;
    child.stdout.on("data", chunk => {
      buffer += chunk;
      let i;
      while ((i = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, i); buffer = buffer.slice(i + 1);
        if (line === "done") progress(); else if (line.startsWith("ROWS ")) result = JSON.parse(line.slice(5));
      }
    });
    child.on("close", code => code === 0 && result ? resolve(result) : reject(new Error(`reader ${reader} exited ${code}`)));
  })))).flat();
}
await wrote;
const elapsed = (performance.now() - windowStart) / 1000;
const p95 = (xs: number[]) => xs.length ? xs.slice().sort((a, b) => a - b)[Math.ceil(xs.length * 0.95) - 1] : null;
const warm = rows.filter(r => r.step > 0);
const count = (xs: Row[]) => xs.reduce<Record<string, number>>((m, r) => (m[r.degradation ?? "none"] = (m[r.degradation ?? "none"] ?? 0) + 1, m), {});
const report = {
  mode, queries: rows.length, readers: 10, reranker: rerankerFromEnv() ? "on" : "off",
  p95_seconds: p95(rows.map(r => r.seconds)), warm_p95_seconds: p95(warm.map(r => r.seconds)), warm_samples: warm.length,
  warm_reranked_p95_seconds: p95(warm.filter(r => r.degradation === null).map(r => r.seconds)),
  max_seconds: Math.max(...rows.map(r => r.seconds)), degradations: count(rows), warm_degradations: count(warm),
  elapsed_query_window_seconds: elapsed, write_overlapped: Boolean(writeWindow), max_context_bytes: Math.max(...rows.map(r => r.bytes)),
  corpus_sha256: sha(readFileSync(join(frozen, "documents.json"), "utf8")),
  limitations: ["Synthetic v1 corpus (one project, 250 pages), not the private eval v2 corpus.",
    "One overlapping write, no index rebuild during the run; visibility p95 is not measured here."],
};
writeFileSync(out, JSON.stringify({ ...report, rows }, null, 1));
process.stdout.write(JSON.stringify(report) + "\n");
await closeQmdReaders();
