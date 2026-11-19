/** QMD 2.8.3 public API, immutable generations and authority-validated RRF. */
import { execFileSync, spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { randomUUID } from "node:crypto";
import { mkdirSync, realpathSync, readFileSync, writeFileSync, renameSync, rmSync, existsSync,
  readdirSync, copyFileSync, mkdtempSync, lstatSync, linkSync } from "node:fs";
import { copyFile } from "node:fs/promises";
import * as z from "zod/v4";
import type { QMDStore } from "@tobilu/qmd";
import { APPROVED_MODEL_SHA256, RERANK_MODEL_SHA256, checkedModel, digest, fileDigestAsync, offlineQmd, prepareOfflineQmd } from "./offline.js";
import { readAuthorityJson } from "./async-authority.js";
import { faultPoint } from "./faults.js";
import { NativeSearchQueue, type SearchPlan, type SearchResult } from "./native-search-queue.js";

const identitySchema = z.object({ authority: z.string(), project: z.string(), epoch: z.string(), sequence: z.number().int().nonnegative() });
const chunkSchema = z.object({ kind: z.enum(["page", "source"]), object: z.string(), revision: z.string(),
  start: z.number().int().positive(), end: z.number().int().positive(), hash: z.string(), title: z.string(), text: z.string(), key: z.string().regex(/^[a-f0-9]{64}$/) });
const snapshotSchema = z.object({ snapshot: identitySchema, documents: z.array(chunkSchema), lexical: z.array(z.string()),
  exact: z.array(z.string()).default([]),
  links: z.record(z.string(), z.array(z.string())), sourceLinks: z.record(z.string(), z.array(z.string())),
  chunkLines: z.literal(32), outboxIds: z.array(z.number().int()) });
const manifestSchema = z.object({ version: z.literal(1), qmdVersion: z.literal("2.8.3"), generation: z.string(),
  target: identitySchema, modelDigest: z.literal(APPROVED_MODEL_SHA256), databaseDigest: z.string(),
  chunkLines: z.literal(32), documents: z.array(chunkSchema), outboxIds: z.array(z.number().int()) });
export type Snapshot = z.infer<typeof snapshotSchema>;
export type Chunk = z.infer<typeof chunkSchema>;
type Manifest = z.infer<typeof manifestSchema>;
// reranker: optional pinned cross-encoder GGUF; when set, the fused top `depth` chunks are reordered by it.
// It runs in its own llama.cpp context (device "vulkan" or "cpu"); embeddings stay on the CPU path.
export type Reranker = { model: string; device?: "vulkan" | "cpu"; depth?: number; docTokens?: number };
const rerankerSchema = z.strictObject({ model: z.string().min(1), device: z.enum(["vulkan", "cpu"]).optional(),
  depth: z.number().int().min(1).max(64).optional(), docTokens: z.number().int().min(32).max(1024).optional() });
/** WIKI_RERANK_MODEL: path to the pinned reranker GGUF (hash-checked on load); unset disables reranking. */
export function rerankerFromEnv(): Reranker | undefined {
  return process.env.WIKI_RERANK_MODEL ? rerankerSchema.parse({ model: process.env.WIKI_RERANK_MODEL }) : undefined;
}
export type Binding = { database: string; project: string; indexRoot: string; model?: string; reranker?: Reranker };
export const recallInputSchema = z.strictObject({
  query: z.string().min(1).max(4096), atLeast: z.string().min(1).max(1024).optional(),
  maxBytes: z.number().int().min(2048).max(24000).default(24000),
  coverage: z.enum(["best-available", "require-hybrid-current"]).default("best-available"),
});
const rpcFile = fileURLToPath(new URL("../mcp/authority_rpc.py", import.meta.url));
export function authorityRpc(binding: Binding, tool: string, args: unknown): unknown {
  return JSON.parse(execFileSync("python3", [rpcFile, resolve(binding.database), binding.project, "worker", tool], {
    input: JSON.stringify(args), encoding: "utf8", maxBuffer: 64 * 1024 * 1024, timeout: 30000,
    stdio: ["pipe", "pipe", "pipe"],
  }));
}
type GenerationLocation = Pick<Binding, "project" | "indexRoot">;
export const generationRoot = (b: GenerationLocation) => join(resolve(b.indexRoot), digest(b.project));
const generationName = (s: string) => /^g-[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(s);
// One persistent helper per process serves kernel flock requests (a fresh open file description per request, so
// locks conflict within this process and across processes alike). The kernel releases every lock if the helper or
// this process dies. This replaces one python3 spawn per acquire and per release.
const LOCK_HELPER = String.raw`
import fcntl, os, sys, threading, time
state, out, held, cancelled = threading.Lock(), threading.Lock(), {}, set()
def reply(text):
    with out:
        sys.stdout.write(text + "\n"); sys.stdout.flush()
def acquire(ident, path):
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        reply("E " + ident); return
    while True:
        with state:
            if ident in cancelled:
                cancelled.discard(ident); os.close(fd); return
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            time.sleep(0.002)
    with state:
        if ident in cancelled:
            cancelled.discard(ident); os.close(fd); return
        held[ident] = fd
    reply("L " + ident)
for line in sys.stdin:
    op, ident, *rest = line.rstrip("\n").split(" ", 2)
    if op == "L":
        threading.Thread(target=acquire, args=(ident, rest[0]), daemon=True).start()
    elif op == "T":
        try:
            fd = os.open(rest[0], os.O_RDWR | os.O_CREAT, 0o600)
        except OSError:
            reply("E " + ident); continue
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd); reply("B " + ident); continue
        with state:
            held[ident] = fd
        reply("T " + ident)
    elif op == "U":
        with state:
            fd = held.pop(ident, None)
            if fd is None:
                cancelled.add(ident)
        if fd is not None:
            os.close(fd)
        reply("U " + ident)
`;
type LockWaiter = { resolve(): void; reject(error: Error): void };
let lockHelper: { child: ReturnType<typeof spawn>; waiters: Map<string, LockWaiter>; buffer: string } | undefined;
function lockHelperProcess() {
  if (lockHelper && lockHelper.child.exitCode === null && !lockHelper.child.killed) return lockHelper;
  const child = spawn("python3", ["-c", LOCK_HELPER], { stdio: ["pipe", "pipe", "ignore"] });
  const helper = { child, waiters: new Map<string, LockWaiter>(), buffer: "" };
  child.stdin!.on("error", () => {});
  child.stdout!.setEncoding("utf8");
  child.stdout!.on("data", (chunk: string) => {
    helper.buffer += chunk;
    let i;
    while ((i = helper.buffer.indexOf("\n")) >= 0) {
      const [op, ident] = helper.buffer.slice(0, i).split(" ");
      helper.buffer = helper.buffer.slice(i + 1);
      if (op === "E") (helper.waiters.get("L" + ident) ?? helper.waiters.get("T" + ident))?.reject(new Error("lock open failed"));
      else if (op === "B") helper.waiters.get("T" + ident)?.reject(new LockBusy());
      else helper.waiters.get(op + ident)?.resolve();
    }
  });
  const fail = () => {
    for (const waiter of [...helper.waiters.values()]) waiter.reject(new Error("generation lock process exited"));
    if (lockHelper === helper) lockHelper = undefined;
  };
  child.once("exit", fail);
  child.once("error", fail);
  lockHelper = helper;
  holdOpen(helper);
  return helper;
}
// The helper keeps this process alive only while a request is outstanding, so idle tools can still exit.
function holdOpen(helper: NonNullable<typeof lockHelper>) {
  const stream = helper.child.stdout as unknown as { ref?: () => void; unref?: () => void };
  if (helper.waiters.size) { helper.child.ref(); stream.ref?.(); } else { helper.child.unref(); stream.unref?.(); }
}
class LockBusy extends Error { constructor() { super("lock busy"); } }
function lockRequest(helper: NonNullable<typeof lockHelper>, op: "L" | "T" | "U", ident: string, path = "") {
  return new Promise<void>((resolve, reject) => {
    const done = (settle: () => void) => { helper.waiters.delete(op + ident); holdOpen(helper); settle(); };
    helper.waiters.set(op + ident, { resolve: () => done(resolve), reject: error => done(() => reject(error)) });
    holdOpen(helper);
    helper.child.stdin!.write(`${op} ${ident}${path ? " " + path : ""}\n`);
  });
}
async function locked<T>(root: string, operation: () => T): Promise<T> {
  mkdirSync(root, { recursive: true });
  const helper = lockHelperProcess();
  const ident = randomUUID();
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([lockRequest(helper, "L", ident, join(root, ".lock")),
      new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error("generation lock timeout")), 5000); })]);
    return operation();
  } finally {
    clearTimeout(timer);
    helper.waiters.get("L" + ident)?.reject(new Error("generation lock abandoned"));
    // Releases a held lock, or cancels a pending acquire; the helper answers either way.
    await lockRequest(helper, "U", ident).catch(() => {});
  }
}
function readManifest(root: string, generation: string): Manifest {
  if (!generationName(generation)) throw new Error("invalid generation pointer");
  const dir = join(root, generation);
  if (lstatSync(dir).isSymbolicLink() || lstatSync(join(dir, "index.sqlite")).isSymbolicLink()) throw new Error("generation symlink denied");
  const manifest = manifestSchema.parse(JSON.parse(readFileSync(join(dir, "manifest.json"), "utf8")));
  if (manifest.generation !== generation || digest(readFileSync(join(dir, "index.sqlite"))) !== manifest.databaseDigest) throw new Error("generation integrity failure");
  return manifest;
}
/** In-process measurement observer for evaluation tools only. It is never set from request data, does not
 * change results, and receives stage timings (ms) plus the ranking lists recall() actually used. */
type RecallPassage = ReturnType<typeof makeRecallPassage>;
type RecallSpan = Pick<Chunk, "kind" | "object" | "revision" | "start" | "end">;
export type RecallTrace = {
  lexical: string[];
  exact: string[];
  vector: string[];
  clauseVectors: string[][];
  clauseWinners: string[];
  fused: string[];
  head: string[];
  rerankAdmission: "disabled" | "ineligible" | "busy" | "unavailable" | "admitted";
  reranked: boolean;
  rerankOrder: string[];
  ranked: string[];
  direct: string[];
  expansionCandidates: string[];
  expanded: string[];
  ordered: string[];
  emitted: string[];
  resolvedCount: number;
  skippedForOverlap: string[];
  skippedForBytes: string[];
  skippedForPassageLimit: string[];
  documents: { key: string; span: RecallSpan; passage: RecallPassage; bytes: number }[];
  baseBytes: number;
  cap: number;
  passageLimit: number;
  degradation: string | null;
};
export type RecallObserver = { stage(name: string, ms: number): void; lists?(data: RecallTrace): void };
let observer: RecallObserver | undefined;
export function observeRecall(next: RecallObserver | undefined) { observer = next; }
async function timed<T>(name: string, operation: () => Promise<T> | T,
  stageObserver: RecallObserver | null | undefined = observer): Promise<T> {
  if (!stageObserver) return operation();
  const start = performance.now();
  try { return await operation(); } finally { stageObserver.stage(name, performance.now() - start); }
}
type VectorHit = { key: string; score: number };
export type GenerationPin = { manifest: Manifest; directory: string; search(query: string): Promise<VectorHit[]>;
  searchMany(queries: string[]): Promise<readonly (readonly VectorHit[])[]>;
  searchPlan(plan: SearchPlan): Promise<SearchResult<VectorHit>>;
  release(): Promise<void> };
export async function acquireGeneration(binding: Binding): Promise<GenerationPin | undefined> {
  const root = generationRoot(binding);
  if (!existsSync(join(root, "current"))) return undefined;
  const requested = performance.now();
  return locked(root, () => {
    observer?.stage("pin.lock", performance.now() - requested);
    const verifyStart = performance.now();
    const generation = readFileSync(join(root, "current"), "utf8").trim();
    const manifest = readManifest(root, generation);
    observer?.stage("pin.verify", performance.now() - verifyStart);
    const leases = join(root, "leases", generation);
    mkdirSync(leases, { recursive: true });
    const lease = join(leases, randomUUID());
    writeFileSync(lease, String(process.pid), { flag: "wx" });
    let released = false;
    let releasePromise: Promise<void> | undefined;
    const pending = new Set<Promise<void>>();
    const pin: GenerationPin = { manifest, directory: join(root, generation),
      search: async query => [...(await pin.searchMany([query]))[0]], searchMany: async queries => {
        if (released) throw new Error("generation reader is closed");
        if (!queries.length) return [];
        if (!binding.model) throw new Error("cached embedding unavailable");
        const [primary, ...supplemental] = queries;
        const result = await pin.searchPlan({ primary, supplemental, deadlineMs: performance.now() + VECTOR_DEADLINE_MS });
        if (result.kind !== "complete") throw new Error("vector search did not finish");
        return [result.primary, ...result.supplemental];
      }, searchPlan: async plan => {
        if (released) throw new Error("generation reader is closed");
        const operation = vectorCandidates(binding, pin, plan);
        pending.add(operation.drained);
        void operation.drained.then(() => pending.delete(operation.drained));
        return operation.result;
    }, release: () => {
      // Close admission synchronously. Wait only for this pin's accepted reads,
      // never a snapshot of the global queue that can admit later readers.
      released = true;
      if (!releasePromise) releasePromise = (async () => {
        await Promise.allSettled([...pending]);
        await locked(root, () => { rmSync(lease, { force: true }); });
      })().catch(error => { releasePromise = undefined; throw error; });
      return releasePromise;
    } };
    return pin;
  });
}
function alive(pid: number): boolean {
  try { process.kill(pid, 0); return true; }
  catch (error: unknown) { return !(error instanceof Error && "code" in error && error.code === "ESRCH"); }
}
export async function cleanupGenerations(binding: Binding): Promise<string[]> {
  const root = generationRoot(binding);
  if (!existsSync(root)) return [];
  const removed = await locked(root, () => {
    const current = existsSync(join(root, "current")) ? readFileSync(join(root, "current"), "utf8").trim() : "";
    const removed = [];
    // Staging directories and pointer temp files of builders that no longer run.
    for (const entry of readdirSync(root)) {
      const owner = /^\.(?:build|pointer)-(\d+)-[a-f0-9-]{36}$/.exec(entry);
      if (!owner || alive(Number(owner[1]))) continue;
      rmSync(join(root, entry), { recursive: true, force: true });
      removed.push(entry);
    }
    for (const generation of readdirSync(root).filter(generationName)) {
      const leases = join(root, "leases", generation);
      if (existsSync(leases)) for (const lease of readdirSync(leases)) {
        const file = join(leases, lease);
        const pid = Number(readFileSync(file, "utf8"));
        if (!Number.isInteger(pid) || pid <= 0) continue;
        try { process.kill(pid, 0); }
        catch (error: unknown) {
          if (error instanceof Error && "code" in error && error.code === "ESRCH") rmSync(file);
        }
      }
      if (generation === current || (existsSync(leases) && readdirSync(leases).length)) continue;
      rmSync(join(root, generation), { recursive: true });
      rmSync(leases, { recursive: true, force: true });
      removed.push(generation);
    }
    return removed;
  });
  await closeQmdReaders();
  return removed;
}
const hasSidecars = (database: string) => ["-wal", "-shm"].some(suffix => existsSync(database + suffix));

/** Copy the immutable generation into a disposable evaluation index root. */
export async function copyGenerationSnapshot(source: Binding, destination: GenerationLocation): Promise<void> {
  if (source.project !== destination.project) throw new Error("snapshot project mismatch");
  const pin = await acquireGeneration(source);
  if (!pin) throw new Error("source generation is missing");
  try {
    const index = join(pin.directory, "index.sqlite");
    if (pin.manifest.target.project !== source.project || hasSidecars(index)) {
      throw new Error("source generation is not an immutable index for this project");
    }
    const root = generationRoot(destination);
    const directory = join(root, pin.manifest.generation);
    const pointer = join(root, `.snapshot-${randomUUID()}`);
    mkdirSync(root, { recursive: true });
    mkdirSync(directory);
    try {
      for (const file of ["index.sqlite", "manifest.json"]) {
        await copyFile(join(pin.directory, file), join(directory, file));
      }
      writeFileSync(pointer, pin.manifest.generation + "\n", { flag: "wx" });
      linkSync(pointer, join(root, "current"));
    } catch (error) {
      rmSync(directory, { recursive: true, force: true });
      throw error;
    } finally {
      rmSync(pointer, { force: true });
    }
  } finally {
    await pin.release();
  }
}

/** Populate a private staging directory. The caller verifies the model and controls promotion. */
export async function stageGenerationIndex(binding: Binding, captured: Pick<Snapshot, "snapshot" | "documents">,
  staging: string, model: string, qmd: Pick<typeof import("@tobilu/qmd"), "createStore" | "Maintenance">) {
  const documents = join(staging, "documents");
  const database = join(staging, "index.sqlite");
  mkdirSync(documents, { recursive: true });
  // QMD embeds the first heading as the title. Use the authority title so an
  // unchanged rendered chunk keeps its content hash even if its key changes.
  for (const chunk of captured.documents) {
    const title = chunk.title.replace(/\s+/g, " ").trim() || chunk.object;
    writeFileSync(join(documents, `${chunk.key}.md`), `# ${title}\n\n${chunk.text}`);
  }

  let baseCount: number | undefined;
  const base = await acquireGeneration(binding);
  try {
    if (base && sameAuthority(base.manifest.target, captured.snapshot)) {
      if (base.manifest.target.sequence > captured.snapshot.sequence) throw new Error("generation promotion would regress");
      const source = join(base.directory, "index.sqlite");
      if (!hasSidecars(source)) {
        // Keep the verified generation leased until the private copy completes.
        // QMD opens only the copy, because even its public opener writes.
        await copyFile(source, database);
        baseCount = base.manifest.documents.length;
      }
    }
  } finally { await base?.release(); }

  async function updateIndex(baseDocuments?: number): Promise<boolean> {
    const store = await qmd.createStore({ dbPath: database, config: {
      models: { embed: model }, collections: { corpus: { path: documents, pattern: "**/*.md" } },
    } });
    const expected = captured.documents.length;
    try {
      if (baseDocuments !== undefined) {
        const baseStatus = await store.getStatus();
        if (baseStatus.totalDocuments !== baseDocuments || baseStatus.needsEmbedding ||
            (baseDocuments > 0 && !baseStatus.hasVectorIndex)) return false;
      }
      const update = await store.update();
      if (update.skipped || update.indexed + update.updated + update.unchanged !== expected) {
        throw new Error("incomplete QMD document update");
      }
      // QMD keys vectors by rendered content and model fingerprint. Normal
      // embed() only visits hashes without complete embeddings.
      const embedded = await store.embed({ chunkStrategy: "regex" });
      if (update.removed || update.updated) {
        // Purge inactive rows and their orphaned vectors, which otherwise
        // compete for candidates in QMD's larger-collection vector search.
        const maintenance = new qmd.Maintenance(store.internal);
        maintenance.cleanupOrphanedVectors();
        maintenance.deleteInactiveDocs();
        maintenance.cleanupOrphanedContent();
      }
      const status = await store.getStatus();
      if (status.totalDocuments !== expected || embedded.errors || status.needsEmbedding ||
          (expected > 0 && !status.hasVectorIndex)) {
        throw new Error("incomplete QMD embedding build");
      }
      return true;
    } finally { await store.close(); }
  }

  if (!await updateIndex(baseCount)) {
    if (hasSidecars(database)) throw new Error("uncheckpointed generation");
    rmSync(database);
    await updateIndex();
  }
  if (hasSidecars(database)) throw new Error("uncheckpointed generation");
}

export async function buildGeneration(binding: Binding) {
  if (!binding.model) throw new Error("explicit approved cached model required");
  const model = checkedModel(binding.model);
  await closeQmdReaders();
  const captured = snapshotSchema.parse(authorityRpc(binding, "wiki_recall_snapshot", { query: "" }));
  const root = generationRoot(binding);
  mkdirSync(root, { recursive: true });
  const generation = `g-${randomUUID()}`;
  // The owner pid in the name lets cleanup reclaim staging left by a crashed build.
  const staging = join(root, `.build-${process.pid}-${randomUUID()}`);
  try {
    const qmd = await offlineQmd(model, join(root, "runtime-cache"));
    const version = JSON.parse(readFileSync(new URL("../../node_modules/@tobilu/qmd/package.json", import.meta.url), "utf8")).version;
    if (version !== "2.8.3") throw new Error("QMD version mismatch");
    await stageGenerationIndex(binding, captured, staging, model, qmd);
    const manifest: Manifest = { version: 1, qmdVersion: "2.8.3", generation, target: captured.snapshot,
      modelDigest: APPROVED_MODEL_SHA256, databaseDigest: digest(readFileSync(join(staging, "index.sqlite"))),
      chunkLines: 32, documents: captured.documents, outboxIds: captured.outboxIds };
    writeFileSync(join(staging, "manifest.json"), JSON.stringify(manifest));
    faultPoint("generation.after-stage");
    await locked(root, () => {
      if (existsSync(join(root, "current"))) {
        const current = readManifest(root, readFileSync(join(root, "current"), "utf8").trim());
        if (sameAuthority(current.target, manifest.target) && current.target.sequence > manifest.target.sequence) throw new Error("generation promotion would regress");
      }
      renameSync(staging, join(root, generation));
      faultPoint("generation.after-rename");
      const pointer = join(root, `.pointer-${process.pid}-${randomUUID()}`);
      writeFileSync(pointer, generation);
      renameSync(pointer, join(root, "current"));
    });
    faultPoint("generation.after-pointer");
    // Only the exact captured outbox/target is acknowledged, and only AFTER promotion.
    authorityRpc(binding, "wiki_index_promoted", manifest);
    return manifest;
  } finally { rmSync(staging, { recursive: true, force: true }); }
}
function sameAuthority(a: Manifest["target"], b: Manifest["target"]) {
  return a.authority === b.authority && a.project === b.project && a.epoch === b.epoch;
}
// Reciprocal-rank fusion constant. Smaller k lets a strong single-branch rank (an exact identifier
// found only lexically) beat many weak ranks that appear in both branches. Tuned on eval v2 development only.
export const RRF_K = 10;
export function fuseRanks(lexical: string[], vector: string[]): string[] {
  const scores = new Map<string, number>();
  const best = new Map<string, number>(), lexicalRank = new Map<string, number>();
  for (const [branch, list] of [[0, lexical], [1, vector]] as const) for (const [rank, key] of [...new Set(list)].entries()) {
    scores.set(key, (scores.get(key) ?? 0) + 1 / (RRF_K + rank + 1));
    best.set(key, Math.min(best.get(key) ?? Infinity, rank));
    if (branch === 0) lexicalRank.set(key, rank);
  }
  // Exact score ties are common (e.g. lexical-only rank r vs vector-only rank r). Break them by content-derived
  // order (best single-branch rank, then lexical rank) before the key, whose revision part is not content-stable.
  return [...scores].sort((a, b) => b[1] - a[1] || best.get(a[0])! - best.get(b[0])! ||
    (lexicalRank.get(a[0]) ?? Infinity) - (lexicalRank.get(b[0]) ?? Infinity) || a[0].localeCompare(b[0])).map(([key]) => key);
}
// One private working copy/model per process. Serialize native embedding calls,
// retain warm weights, and close before switching generations or running cleanup.
let cachedReader: { key: string; store: QMDStore; work: string } | undefined;
const vectorQueue = new NativeSearchQueue<VectorHit>({ maxRequests: 32 });
const VECTOR_DEADLINE_MS = 30_000;
async function disposeReader() {
  const previous = cachedReader;
  cachedReader = undefined;
  if (previous) try { await previous.store.close(); }
  finally { rmSync(previous.work, { recursive: true, force: true }); }
}
export async function closeQmdReaders(): Promise<void> {
  // Dispose both caches even if one fails; report the first failure afterwards.
  const ranker = rankerQueue.then(disposeRanker);
  rankerQueue = ranker.then(() => {}, () => {});
  const results = await Promise.allSettled([vectorQueue.barrier(disposeReader), ranker]);
  const failed = results.find(r => r.status === "rejected");
  if (failed) throw (failed as PromiseRejectedResult).reason;
}
async function ensureReader(binding: Binding, pin: GenerationPin, stageObserver: RecallObserver | null): Promise<QMDStore> {
  const model = binding.model;
  if (!model) throw new Error("cached embedding unavailable");
  const events: [string, number][] = [];
  const buffer: RecallObserver | null = stageObserver && {
    stage(name, ms) { events.push([name, ms]); },
  };
  try {
    const load = await timed("vector.model-verify",
      () => prepareOfflineQmd(model, join(generationRoot(binding), "runtime-cache")), buffer);
    return await timed("vector.reader-setup", async () => {
      const qmd = await load();
      const key = pin.directory + ":" + resolve(model);
      if (cachedReader?.key !== key) await disposeReader();
      if (!cachedReader) {
        // The supported public opener creates WAL/SHM. Never open the generation.
        const work = mkdtempSync(join(tmpdir(), "wiki-qmd-reader-"));
        try {
          const path = join(work, "index.sqlite");
          copyFileSync(join(pin.directory, "index.sqlite"), path);
          cachedReader = { key, work, store: await qmd.createStore({ dbPath: path }) };
        } catch (error) { rmSync(work, { recursive: true, force: true }); throw error; }
      }
      return cachedReader.store;
    }, buffer);
  } finally {
    // Publish after setup settles so the observer cannot interfere between verification and setup.
    for (const [name, ms] of events) stageObserver?.stage(name, ms);
  }
}
function vectorCandidates(binding: Binding, pin: GenerationPin, plan: SearchPlan) {
  // A timed-out dispatch can settle after the caller switches observers.
  const stageObserver = observer ?? null;
  let queued = performance.now();
  let searchStore: QMDStore | undefined;
  return vectorQueue.schedule(plan, async (query, { deadlineMs }) => {
    stageObserver?.stage("vector.queue", performance.now() - queued);
    // Reuse this request's checked store only while its native reader is still installed.
    if (!searchStore || cachedReader?.store !== searchStore) {
      searchStore = await ensureReader(binding, pin, stageObserver);
    }
    if (performance.now() >= deadlineMs) throw new Error("vector search deadline exceeded");
    try {
      const store = searchStore;
      const hits = await timed("vector.search", () => store.searchVector(query, { limit: 40, collection: "corpus" }), stageObserver);
      return hits.flatMap(hit => {
        const match = /^qmd:\/\/corpus\/([a-f0-9]{64})\.md$/.exec(hit.filepath);
        return match ? [{ key: match[1], score: hit.score }] : [];
      });
    } finally { queued = performance.now(); }
  });
}
export function compoundQueryParts(query: string): string[] {
  const parts = query.split(/(?:;\s*|\s+(?:and|whereas|versus)\s+)(?=(?:what|which|how|why|when|where|who|is|are|does|do|can|should|could|would)\b)/iu)
    .map(part => part.trim());
  return parts.length === 2 && parts.every(part => part.split(/\s+/u).length >= 4) ? parts : [];
}
export const RERANK_DEPTH = 24; // D14: 30 -> 24 (dev p95 8.0 s -> 5.7 s, recall 0.9706 -> 0.9669, multi-page 0.90 -> 0.95)
export const RERANK_DOC_TOKENS = 512;
const RERANK_CONTEXT_TOKENS = 2048, RERANK_TEMPLATE_TOKENS = 128;
type RankingContext = { rankAll(query: string, texts: string[]): Promise<number[]> };
type Tokenizer = { tokenize(text: string): unknown[]; detokenize(tokens: unknown[]): string };
let cachedRanker: { key: string; dispose(): Promise<void>; model: Tokenizer; context: RankingContext } | undefined;
let rankerQueue: Promise<void> = Promise.resolve();
async function disposeRanker() {
  const previous = cachedRanker;
  cachedRanker = undefined;
  await previous?.dispose();
}
/** Run every cleanup step even if an earlier one fails; rethrow the first failure. */
async function unwind(steps: (() => Promise<unknown> | unknown)[]) {
  let first: unknown;
  for (const step of steps) try { await step(); } catch (error) { first ??= error; }
  if (first !== undefined) throw first;
}
// The GPU serves one ranking at a time, machine-wide. Admission is a non-blocking exclusive lock file
// shared by every process of this user: a recall that finds it held keeps the fused order
// (degradation "reranker-busy") instead of queueing, so concurrent recall latency stays bounded.
export function rerankLockPath(): string {
  return process.env.WIKI_RERANK_LOCK ?? join(tmpdir(), `wiki-reranker-${process.getuid?.() ?? "user"}.lock`);
}
/** Non-blocking machine-wide admission: a kernel flock on a stable file, held through the persistent lock helper.
 * The kernel releases it if the holder dies, so there is no stale-owner state to reclaim. Resolves to a release
 * function, or undefined when another holder (any process, including this one) has it. */
export async function tryRerankLock(path = rerankLockPath()): Promise<(() => Promise<void>) | undefined> {
  const helper = lockHelperProcess();
  const ident = randomUUID();
  try { await lockRequest(helper, "T", ident, path); }
  catch (error) { if (error instanceof LockBusy) return undefined; throw error; }
  let released = false;
  return async () => { if (!released) { released = true; await lockRequest(helper, "U", ident).catch(() => {}); } };
}
// After reranking, the first chunk of each of the fused top PROTECT_FUSED objects stays in front: both branches
// agreeing near the top is evidence the cross-encoder can wrongly demote (eval v2 development trace, D12).
export const PROTECT_FUSED = 2;
/** Protected keys first (exact identifier hits, then the first chunk of each of the top `protectFused` fused objects),
 * then the remaining order. Only authorized keys can be protected. */
export function protectFront(ranked: string[], exact: string[], fused: string[], protectFused: number,
  objectOf: (key: string) => string | undefined, clauseWinners: string[] = []): string[] {
  const front: string[] = [];
  const objects = new Set<string>();
  for (const key of exact) {
    const object = objectOf(key);
    if (object !== undefined && !front.includes(key)) { front.push(key); objects.add(object); }
  }
  let taken = 0;
  for (const key of fused) {
    if (taken >= protectFused) break;
    const object = objectOf(key);
    if (object === undefined || objects.has(object)) continue;
    front.push(key); objects.add(object); taken++;
  }
  for (const key of clauseWinners) {
    const object = objectOf(key);
    if (object === undefined || objects.has(object)) continue;
    front.push(key); objects.add(object);
  }
  const inFront = new Set(front);
  return [...front, ...ranked.filter(key => !inFront.has(key))];
}
/** Reranked keys first (in reranker order), then the rest of the fused order. `order` must be an exact permutation of `head`. */
export function applyRerank(ranked: string[], head: string[], order: string[]): string[] {
  const headSet = new Set(head);
  if (headSet.size !== head.length || order.length !== head.length || new Set(order).size !== order.length || !order.every(key => headSet.has(key))) {
    throw new Error("reranker result does not match its candidates");
  }
  return [...order, ...ranked.filter(key => !headSet.has(key))];
}
/** Order chunk keys by score; exactly one finite score per chunk, ties keep the fused order. */
export function orderByScores(keys: string[], scores: unknown): string[] {
  if (!Array.isArray(scores) || scores.length !== keys.length || !scores.every(x => typeof x === "number" && Number.isFinite(x))) {
    throw new Error("reranker returned malformed scores");
  }
  return keys.map((key, i) => ({ key, score: scores[i] as number, i })).sort((a, b) => b.score - a.score || a.i - b.i).map(x => x.key);
}
async function loadRanker(path: string, device: "vulkan" | "cpu", key: string) {
  // Verify and load the same bytes: copy to a private directory, hash the copy, load the copy.
  const work = mkdtempSync(join(tmpdir(), "wiki-reranker-"));
  const cleanup: (() => Promise<unknown> | unknown)[] = [() => rmSync(work, { recursive: true, force: true })];
  try {
    const copy = join(work, "reranker.gguf");
    copyFileSync(path, copy);
    if (await fileDigestAsync(copy) !== RERANK_MODEL_SHA256) throw new Error("unapproved cached reranker hash");
    const { getLlama } = await import("node-llama-cpp");
    const llama = await getLlama({ gpu: device === "cpu" ? false : "vulkan", build: "never" });
    cleanup.unshift(() => llama.dispose());
    const model = await llama.loadModel({ modelPath: copy });
    cleanup.unshift(() => model.dispose());
    const context = await model.createRankingContext({ contextSize: RERANK_CONTEXT_TOKENS });
    cleanup.unshift(() => context.dispose());
    return { key, model: model as unknown as Tokenizer, context: context as unknown as RankingContext, dispose: () => unwind(cleanup) };
  } catch (error) {
    await unwind(cleanup).catch(() => {});
    throw error;
  }
}
/** Reorder chunk keys by cross-encoder relevance; keys are authorized snapshot chunks only. */
function rerankKeys(reranker: Reranker, query: string, chunks: Chunk[]): Promise<string[]> {
  const queued = performance.now();
  const result = rankerQueue.then(async () => {
    observer?.stage("rerank.queue", performance.now() - queued);
    const path = realpathSync(reranker.model);
    const device = reranker.device ?? "vulkan";
    const key = path + ":" + device;
    if (cachedRanker?.key !== key) await disposeRanker();
    if (!cachedRanker) cachedRanker = await timed("rerank.load", () => loadRanker(path, device, key));
    const { model, context } = cachedRanker;
    // Query, template and document must fit the 2,048-token ranking context together.
    const budget = RERANK_CONTEXT_TOKENS - RERANK_TEMPLATE_TOKENS - model.tokenize(query).length;
    if (budget < 64) throw new Error("query too long for the ranking context");
    const limit = Math.min(reranker.docTokens ?? RERANK_DOC_TOKENS, budget);
    const texts = chunks.map(c => {
      const tokens = model.tokenize(`${c.title}\n${c.text}`);
      return tokens.length <= limit ? `${c.title}\n${c.text}` : model.detokenize(tokens.slice(0, limit));
    });
    return orderByScores(chunks.map(c => c.key), await timed("rerank.score", () => context.rankAll(query, texts)));
  });
  rankerQueue = result.then(() => {}, () => {});
  return result;
}
export async function recall(binding: Binding, input: z.input<typeof recallInputSchema>) {
  return timed("total", () => recallOnce(binding, input));
}

const PASSAGE_LIMIT = 10;
const encodedBytes = (value: unknown) => Buffer.byteLength(JSON.stringify(value));

export function recallSpansOverlap(left: RecallSpan, right: RecallSpan): boolean {
  return left.kind === right.kind && left.object === right.object && left.revision === right.revision &&
    left.start <= right.end && right.start <= left.end;
}

function makeRecallPassage(chunk: Chunk, snapshot: Snapshot["snapshot"]) {
  return {
    kind: chunk.kind === "page" ? "current-page" : "source-evidence",
    ...(chunk.kind === "page" ? { page: chunk.object } : { source: chunk.object }),
    revision: chunk.revision, start: chunk.start, end: chunk.end, hash: chunk.hash, title: chunk.title, text: chunk.text,
    citation: { kind: chunk.kind, ...(chunk.kind === "page" ? { page: chunk.object } : { source: chunk.object }),
      revision: chunk.revision, start: chunk.start, end: chunk.end, hash: chunk.hash },
    ...(chunk.kind === "page" ? { snapshot } : {}),
  };
}
async function recallOnce(binding: Binding, input: z.input<typeof recallInputSchema>) {
  input = recallInputSchema.parse(input);
  const cap = input.maxBytes ?? 24000;
  if (!Number.isInteger(cap) || cap < 2048 || cap > 24000) throw new Error("recall byte cap must be 2048..24000");
  let pin: GenerationPin | undefined;
  let deferRelease = false;
  const vectorDeadline = performance.now() + VECTOR_DEADLINE_MS;
  let unavailable: string | undefined;
  const reportDegradation = (reason: string) => {
    unavailable = unavailable ? `${unavailable}+${reason}` : reason;
  };
  try { pin = await timed("pin", () => acquireGeneration(binding)); }
  catch (error) {
    // A lock that cannot be taken in time is load, not corruption; keep the two apart for diagnosis.
    unavailable = /generation lock/.test(String((error as Error)?.message)) ? "generation-lock-unavailable" : "generation-integrity";
  }
  try {
    // The generation reference is retained before acquiring R, including model work.
    const captured = await timed("snapshot", async () => snapshotSchema.parse(await readAuthorityJson(
      ["python3", rpcFile, resolve(binding.database), binding.project, "worker", "wiki_recall_snapshot"], { query: input.query })));
    const target = captured.snapshot;
    if (input.atLeast) {
      const requested = /^(.*):([^:]+):(\d+)$/.exec(input.atLeast);
      if (requested?.[1] === target.project && requested[2] !== target.epoch) {
        return { kind: "not-ready", reason: "stale-epoch", index: { kind: "absent" }, snapshot: target };
      }
      if (!requested || requested[1] !== target.project || !Number.isSafeInteger(Number(requested[3])) || Number(requested[3]) > target.sequence) {
        return { kind: "not-ready", reason: "requested-snapshot-unavailable", index: { kind: "absent" }, snapshot: target };
      }
    }
    const usable = pin && sameAuthority(pin.manifest.target, target) && pin.manifest.target.sequence <= target.sequence ? pin : undefined;
    let coverage: "lexical-only" | "hybrid-current" | "hybrid-stale" = "lexical-only";
    const index = usable ? { kind: "available", generation: usable.manifest.generation,
      indexedThrough: usable.manifest.target, modelDigest: usable.manifest.modelDigest } : { kind: "absent" };
    if (input.coverage === "require-hybrid-current" && (!usable || usable.manifest.target.sequence !== target.sequence || !binding.model)) {
      return { kind: "not-ready", reason: usable ? "index-lag-or-model-unavailable" : unavailable ?? "index-unavailable", index, snapshot: target };
    }
    let hitGroups: readonly (readonly VectorHit[])[] = [];
    if (usable) {
      try {
        const supplemental = compoundQueryParts(input.query);
        const search = await timed("vector", () => usable.searchPlan({
          primary: input.query, supplemental, deadlineMs: vectorDeadline,
        }));
        deferRelease = search.kind !== "complete" && search.reason === "deadline";
        if (search.kind === "primary-unavailable") {
          reportDegradation(search.reason === "reader-error" ? "model-or-vector-unavailable" : `vector-${search.reason}`);
        } else {
          const clauses = search.kind === "complete" ? search.supplemental
            : supplemental.map((_query, i) => search.completed.get(i) ?? []);
          hitGroups = [search.primary, ...clauses];
          if (search.kind === "supplemental-incomplete") reportDegradation(`vector-supplemental-${search.reason}`);
          coverage = usable.manifest.target.sequence === target.sequence ? "hybrid-current" : "hybrid-stale";
        }
      } catch { reportDegradation("model-or-vector-unavailable"); }
    }
    if (input.coverage === "require-hybrid-current" && coverage !== "hybrid-current") {
      return { kind: "not-ready", reason: unavailable ?? "model-unavailable", index, snapshot: target };
    }
    const authorized = new Map(captured.documents.map(chunk => [chunk.key, chunk]));
    // Match immutable manifest identity too, never use provider snippets/docids as citations.
    const manifestKeys = new Map(usable?.manifest.documents.map(chunk => [chunk.key, chunk]) ?? []);
    // Equal scores (identical chunk text) are ordered by content-derived identity, not by provider row order,
    // which follows the key and so changes when identical content is loaded again.
    const stable = (key: string) => { const c = authorized.get(key)!; return [c.kind, c.object, String(c.start).padStart(9, "0"), key].join("\u0000"); };
    const [vector = [], ...clauseVectors] = hitGroups.map(hits => hits
      .filter(hit => authorized.has(hit.key) && manifestKeys.get(hit.key)?.hash === authorized.get(hit.key)?.hash)
      .sort((a, b) => b.score - a.score || stable(a.key).localeCompare(stable(b.key))).map(hit => hit.key));
    const clauseWinners = clauseVectors.flatMap(keys => keys.slice(0, 1));
    let ranked = fuseRanks(captured.lexical, vector);
    const fused = ranked;
    let head: string[] = [];
    let reranked = false;
    let rerankAdmission: RecallTrace["rerankAdmission"] = binding.reranker ? "ineligible" : "disabled";
    if (binding.reranker && usable && coverage !== "lexical-only") {
      head = ranked.filter(key => authorized.has(key)).slice(0, binding.reranker.depth ?? RERANK_DEPTH);
      let release: (() => Promise<void>) | undefined;
      try { rerankerSchema.parse(binding.reranker); release = await tryRerankLock(); }
      catch { reportDegradation("reranker-unavailable"); rerankAdmission = "unavailable"; }
      if (!release) {
        if (rerankAdmission !== "unavailable") rerankAdmission = "busy";
        if (rerankAdmission === "busy") reportDegradation("reranker-busy");
      }
      else {
        rerankAdmission = "admitted";
        try {
          const order = await timed("rerank", () => rerankKeys(binding.reranker!, input.query, head.map(key => authorized.get(key)!)));
          ranked = applyRerank(ranked, head, order);
          reranked = true;
        } catch { reportDegradation("reranker-unavailable"); } finally { await release(); }
      }
    }
    const rerankOrder = ranked;
    const objectOf = (key: string) => { const c = authorized.get(key); return c ? JSON.stringify([c.kind, c.object, c.revision]) : undefined; };
    ranked = protectFront(ranked, captured.exact, fused, reranked ? PROTECT_FUSED : 0, objectOf, clauseWinners);
    const selected: Chunk[] = [];
    const skippedForOverlap: string[] = [], expansionCandidates: string[] = [];
    const traceLists = observer?.lists;
    const add = (key: string) => {
      const chunk = authorized.get(key);
      if (!chunk) return;
      if (selected.some(p => recallSpansOverlap(p, chunk))) {
        if (traceLists) skippedForOverlap.push(key);
        return;
      }
      selected.push(chunk);
    };
    for (const key of ranked) add(key);
    const direct = selected.length;
    // One-hop expansion uses only snapshot-authorized targets, never current/new heads.
    for (const chunk of [...selected]) if (chunk.kind === "page") {
      for (const candidate of captured.documents) {
        if ((candidate.kind === "page" && captured.links[chunk.object]?.includes(candidate.object)) ||
            (candidate.kind === "source" && captured.sourceLinks[chunk.object]?.includes(candidate.revision))) {
          if (traceLists) expansionCandidates.push(candidate.key);
          add(candidate.key);
        }
      }
    }
    const first: Chunk[] = [], remainder: Chunk[] = [];
    const seenObjects = new Set<string>();
    for (const chunk of selected) {
      const object = JSON.stringify([chunk.kind, chunk.object, chunk.revision]);
      (seenObjects.has(object) ? remainder : first).push(chunk);
      seenObjects.add(object);
    }
    const makePassage = (chunk: Chunk) => makeRecallPassage(chunk, target);
    const passages: RecallPassage[] = [];
    const result = { kind: "context", coverage, evidence: { kind: "candidates", passages }, index, snapshot: target,
      ...(unavailable ? { degradation: unavailable } : {}) };
    const baseBytes = encodedBytes(result);
    let bytes = baseBytes;
    const chosen: Chunk[] = [];
    const skippedForBytes: string[] = [], emitted: string[] = [];
    const ordered = [...first, ...remainder];
    let position = 0;
    for (; position < ordered.length && passages.length < PASSAGE_LIMIT; position++) {
      const chunk = ordered[position];
      const passage = makePassage(chunk);
      const size = encodedBytes(passage) + Number(passages.length > 0);
      if (bytes + size > cap) { skippedForBytes.push(chunk.key); continue; }
      bytes += size;
      passages.push(passage); chosen.push(chunk); emitted.push(chunk.key);
    }
    // Size against the captured snapshot, then resolve only the passages that can be emitted.
    // The authority must return the identical immutable body spans before any result is exposed.
    const resolved = await timed("resolve", async () => z.array(chunkSchema).parse(await readAuthorityJson(
      ["python3", rpcFile, resolve(binding.database), binding.project, "worker", "wiki_recall_resolve"], {
        authority: target.authority, epoch: target.epoch, passages: chosen,
      })));
    if (resolved.length !== chosen.length || resolved.some((chunk, i) => chunk.key !== chosen[i].key ||
      JSON.stringify(makePassage(chunk)) !== JSON.stringify(passages[i]))) throw new Error("resolved passage differs from captured snapshot");
    if (traceLists) observer?.lists?.({
      lexical: captured.lexical.filter(key => authorized.has(key)), exact: captured.exact.filter(key => authorized.has(key)),
      vector, clauseVectors, clauseWinners, fused, head, rerankAdmission, reranked, rerankOrder, ranked,
      direct: selected.slice(0, direct).map(c => c.key), expanded: selected.slice(direct).map(c => c.key),
      ordered: ordered.map(c => c.key), emitted, resolvedCount: resolved.length, expansionCandidates: [...new Set(expansionCandidates)],
      skippedForOverlap: [...new Set(skippedForOverlap)].filter(key => !selected.some(c => c.key === key)),
      skippedForBytes, skippedForPassageLimit: ordered.slice(position).map(c => c.key),
      documents: captured.documents.map(c => {
        const passage = makePassage(c);
        const { kind, object, revision, start, end } = c;
        return { key: c.key, span: { kind, object, revision, start, end }, passage, bytes: encodedBytes(passage) };
      }),
      baseBytes, cap, passageLimit: PASSAGE_LIMIT, degradation: unavailable ?? null,
    });
    if (selected.length && !passages.length) return { kind: "capacity", reason: "complete-cited-span-does-not-fit", index, snapshot: target };
    if (!passages.length) result.evidence.kind = "no-matches";
    if (encodedBytes(result) > cap) throw new Error("recall metadata exceeds cap");
    return result;
  } finally {
    const release = pin?.release();
    if (deferRelease) void release?.catch(() => {});
    else await release;
  }
}
