/** Ten-reader v2 performance measurement on a disposable copy of the frozen holdout index. */
import { AsyncLocalStorage } from "node:async_hooks";
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { cpSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { hostname, platform, arch, loadavg } from "node:os";
import { join, resolve } from "node:path";
import { performance } from "node:perf_hooks";
import { promisify } from "node:util";
import { fileDigestAsync } from "../retrieval/offline.js";
import { closeQmdReaders, generationRoot, observeRecall, recall } from "../retrieval/qmd-integration.js";
import { evaluationRerankerSettings } from "./g2-reranker-profile.js";

const execute = promisify(execFile);
const [source, output, model, reranker] = process.argv.slice(2, 6).map(value => resolve(value));
const subset = process.argv[6] === "--development" ? "development" : "holdout";
if (!source || !output || !model || !reranker) throw new Error("expected run directory, output directory and two pinned model files");
const root = process.cwd();
const clock = () => performance.timeOrigin + performance.now();
const sha = (value: string | Buffer) => createHash("sha256").update(value).digest("hex");
const quantile = (values: number[]) => values.sort((a, b) => a - b)[Math.ceil(0.95 * values.length) - 1];
const seconds = (start: number, end = clock()) => (end - start) / 1000;
const info = JSON.parse(readFileSync(join(source, "retrieval-run.json"), "utf8"));
const reportBytes = readFileSync(join(source, "report.json"));
if (info.report_sha256 !== sha(reportBytes)) throw new Error("holdout report does not match its provenance");
const report = JSON.parse(reportBytes.toString("utf8"));
const rankingBytes = readFileSync(join(source, "raw.json"));
if (report.raw_rankings_sha256 !== sha(rankingBytes)) throw new Error("holdout rankings do not match the report");
const initialBuildSeconds = JSON.parse(rankingBytes.toString("utf8")).buildSeconds;
const questions: { id: string; query: string; project: string }[] = JSON.parse(readFileSync(join(source, "questions.json"), "utf8"));
const candidates = questions.filter(q => q.project === "main").sort((a, b) => sha(a.id).localeCompare(sha(b.id))).slice(0, 110);
if (candidates.length !== 110 || report.subset !== subset) throw new Error("a matching v2 partition and 110 questions are required");
const commit = (await execute("git", ["rev-parse", "HEAD"], { timeout: 5_000 })).stdout.trim();
if (commit !== info.identity.commit || (subset === "holdout" && info.identity.dirty)) {
  throw new Error("benchmark must use the original candidate");
}
const dirty = (await execute("git", ["status", "--porcelain", "--untracked-files=all"], { timeout: 5_000 })).stdout
  .trimEnd().split("\n").filter(line => line && !line.startsWith("?? .verification/"));
if (subset === "holdout" && dirty.length) throw new Error("tracked release candidate changed before measurement");

const rerankerSettings = evaluationRerankerSettings(subset === "development");
const rerankerSha = await fileDigestAsync(reranker);
mkdirSync(output, { mode: 0o700 });
const database = join(output, "authority.db");
const indexRoot = join(output, "indexes");
const project = "main";
const binding = { database, indexRoot, project, model, reranker: { model: reranker, ...rerankerSettings } };
const python = join(root, ".venv/bin/python");
const snapshot = await execute(python, ["-B", "-c", `
import sqlite3, sys
from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).as_uri() + "?mode=ro", uri=True) as source:
    with sqlite3.connect(sys.argv[2]) as dest:
        source.backup(dest)
        print(dest.execute("SELECT count(*) FROM page_heads WHERE project='main'").fetchone()[0])
`, join(source, "authority.db"), database], { timeout: 20_000 });
const pages = Number(snapshot.stdout.trim());
const originalRoot = generationRoot({ ...binding, indexRoot: join(source, "indexes") });
const copiedRoot = generationRoot(binding);
const generation = readFileSync(join(originalRoot, "current"), "utf8").trim();
if (!/^g-[0-9a-f-]{36}$/.test(generation)) throw new Error("unexpected holdout generation name");
mkdirSync(copiedRoot, { recursive: true });
cpSync(join(originalRoot, generation), join(copiedRoot, generation), { recursive: true, errorOnExist: true });
writeFileSync(join(copiedRoot, "current"), generation + "\n");
const buildArgs = ["node_modules/tsx/dist/cli.mjs", "src/retrieval/build-index.ts", database, project, indexRoot, model];
const build = async () => {
  const start = clock();
  const result = await execute(process.execPath, buildArgs, { timeout: 720_000 });
  return { seconds: seconds(start), result: JSON.parse(result.stdout.trim()) };
};
const publication = async () => {
  const start = clock();
  const { stdout } = await execute(python, ["-B", "-c", `
import json, sys, time
sys.path.insert(0, "src/authority")
from authority import ChangeKind, DecisionKind, connect_knowledge
store = connect_knowledge(sys.argv[1], "main")
records = []
for i in range(10):
    page = f"phase-p-visibility-{i}"
    title = f"Phase P synthetic visibility fixture {i}"
    base = store.create_page("main", page, title, "A synthetic baseline.", "owner")
    marker = f"WIKIPERFVISIBILITY{i:03}"
    pending = store.propose("main", page, base.revision, ChangeKind.REPLACE, title,
                            f"Synthetic publication marker {marker}.", "worker", [])
    started = time.time_ns()
    outcome = store.decide("main", pending.key, DecisionKind.PUBLISH)
    committed = time.time_ns()
    if outcome.kind != "committed":
        raise RuntimeError("synthetic publication did not commit")
    records.append({"page": page, "marker": marker, "revision": outcome.page_revision,
                    "committedAt": committed / 1e6, "decisionSeconds": (committed - started) / 1e9})
print(json.dumps(records))
`, database], { timeout: 20_000 });
  return { start, end: clock(), records: JSON.parse(stdout) as {
    page: string; marker: string; revision: string; committedAt: number; decisionSeconds: number
  }[] };
};
const startLoad = loadavg();
console.log(`Cloned the verified ${subset} generation for ${pages} main-project pages.`);

type Stages = Record<string, number>;
const contexts = new AsyncLocalStorage<Stages>();
let completed = 0;
observeRecall({
  stage(name, ms) {
    const current = contexts.getStore();
    if (current) current[name] = (current[name] ?? 0) + ms;
  },
});
const sample = async ({ id, query }: typeof candidates[number], reader: number, step: number) => {
  const stage: Stages = {};
  const start = clock();
  const result = await contexts.run(stage, () => recall(binding, { query, coverage: "best-available" })).catch(() => null);
  const end = clock();
  if (step >= 0 && ++completed % 25 === 0) console.log(`Timed ${completed}/100 warm recalls.`);
  return { id, reader, step, start, end, seconds: seconds(start, end), result: result?.kind ?? "error",
    coverage: result && "coverage" in result ? result.coverage : null,
    degradation: result && "degradation" in result ? result.degradation : null, stage,
    bytes: result ? Buffer.byteLength(JSON.stringify(result)) : 0,
    passages: result && "evidence" in result ? result.evidence.passages : [] };
};

async function processTreeRss(pid: number): Promise<number> {
  const base = `/proc/${pid}`;
  const [status, children] = await Promise.all([
    readFile(`${base}/status`, "utf8").catch(() => ""),
    readFile(`${base}/task/${pid}/children`, "utf8").catch(() => ""),
  ]);
  const own = Number(/^VmRSS:\s+(\d+)\s+kB/m.exec(status)?.[1] ?? 0) * 1024;
  const descendants = await Promise.all((children.match(/\d+/g) ?? []).map(value => processTreeRss(Number(value))));
  return descendants.reduce((sum, bytes) => sum + bytes, own);
}

let treePeak = 0;
let sampling: Promise<void> | undefined;
const sampler = setInterval(() => {
  sampling ??= processTreeRss(process.pid).then(bytes => { treePeak = Math.max(treePeak, bytes); })
    .finally(() => { sampling = undefined; });
}, 250);
sampler.unref();
try {
  const warmup = await Promise.all(candidates.slice(0, 10).map((q, i) => sample(q, i, -1)));
  if (warmup.some(row => row.coverage !== "hybrid-current")) throw new Error("warmup did not exercise current hybrid recall");
  const timed = Promise.all(Array.from({ length: 10 }, async (_, reader) => {
    const rows = [];
    const start = 10 + reader * 10;
    for (const [step, question] of candidates.slice(start, start + 10).entries()) {
      rows.push(await sample(question, reader, step));
    }
    return rows;
  }));
  const visible = (async () => {
    const writes = await publication();
    console.log("Ten synthetic publications committed. Building the replacement index.");
    const promotion = await build();
    const rows = await Promise.all(writes.records.map(async write => {
      const result = await recall(binding, { query: write.marker, coverage: "require-hybrid-current" });
      const exact = "coverage" in result && result.coverage === "hybrid-current"
        && result.evidence.passages.some(item => "page" in item && item.page === write.page
          && "revision" in item && item.revision === write.revision
          && "text" in item && typeof item.text === "string" && item.text.includes(write.marker));
      return { commit_at: write.committedAt, seconds: seconds(write.committedAt),
        decision_seconds: write.decisionSeconds, exact };
    }));
    return { promotion_seconds: promotion.seconds, writes, rows };
  })();
  const results = await Promise.allSettled([timed, visible]);
  const [readers, writes] = results;
  if (readers.status === "rejected") throw readers.reason;
  if (writes.status === "rejected") throw writes.reason;
  const rows = readers.value.flat();
  const visibility = writes.value.rows;
  clearInterval(sampler);
  await sampling;
  const overlap = new Set(rows.filter(row => visibility.some(write =>
    row.start <= write.commit_at && write.commit_at <= row.end)).map(row => row.reader)).size;
  const { model: _rerankerPath, ...observedReranker } = binding.reranker;
  const measurement = {
    commit, manifest_sha256: report.manifest_sha256, embedding_sha256: report.model_sha256,
    reranker_sha256: rerankerSha, reranker: observedReranker,
    script_sha256: sha(readFileSync(new URL(import.meta.url))), scope: "explicit local build and promotion; one batch",
    machine_sha256: sha(hostname()), platform: platform(), arch: arch(), load_average: startLoad,
    pages, readers: 10, warm_samples: rows.length, readers_overlapping_publication: overlap,
    first_query_p95_seconds: quantile(warmup.map(row => row.seconds)),
    warm_recall_p95_seconds: quantile(rows.map(row => row.seconds)),
    vector_queue_p95_ms: quantile(rows.map(row => row.stage["vector.queue"] ?? 0)),
    service_peak_rss_bytes: process.resourceUsage().maxRSS * 1024,
    sampled_process_tree_peak_rss_bytes: treePeak || null,
    elapsed_holdout_index_build_seconds: initialBuildSeconds, elapsed_rebuild_seconds: writes.value.promotion_seconds,
    publications: visibility.length, exact_current_publications: visibility.filter(row => row.exact).length,
    committed_to_observed_hybrid_p95_seconds: quantile(visibility.map(row => row.seconds)),
    curator_decision_p95_seconds: quantile(visibility.map(row => row.decision_seconds)),
    context_failures: rows.filter(row => row.result !== "context").length,
    degraded_recalls: rows.filter(row => row.degradation || row.coverage !== "hybrid-current").length,
  };
  writeFileSync(join(output, "performance.json"), JSON.stringify({ ...measurement, rows, visibility }, null, 2) + "\n");
  console.log(JSON.stringify(measurement, null, 2));
} finally {
  clearInterval(sampler);
  observeRecall(undefined);
  await closeQmdReaders();
}
