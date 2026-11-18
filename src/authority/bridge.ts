/** Validated synchronous JSON boundary. No shell, evaluated commands or success fallbacks. */
import { spawnSync } from "node:child_process";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import * as z from "zod/v4";

const rpc = fileURLToPath(new URL("./bridge_rpc.py", import.meta.url));
const errorSchema = z.strictObject({ kind: z.literal("error"), error: z.string(), message: z.string() });
export type BridgeError = z.infer<typeof errorSchema>;
const connectionSchema = z.strictObject({ kind: z.literal("connected"), project: z.string(), dbPath: z.string(), epoch: z.string(), sequence: z.number().int().nonnegative() });
export type ConnectedStore = z.infer<typeof connectionSchema>;
const pageSchema = z.strictObject({ kind: z.literal("page"), page: z.string(), revision: z.string(), hash: z.string().regex(/^h:[a-f0-9]{64}$/), title: z.string(), markdown: z.string(), state: z.enum(["active", "retired"]) });
const proposalSchema = z.strictObject({ kind: z.literal("pending"), key: z.string(), proposal: z.string(), digest: z.string() });
const decisionSchema = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("committed"), page_revision: z.string(), project_revision: z.string() }),
  z.object({ kind: z.literal("conflict"), current: z.string().nullable() }),
  z.object({ kind: z.literal("rejected"), reason: z.string() }),
]);
const operationSchema = z.union([
  z.strictObject({ kind: z.literal("unknown") }),
  z.strictObject({ kind: z.literal("operation"), key: z.string(), project: z.string(), principal: z.string(), request_digest: z.string(), result_digest: z.string(), status: z.enum(["submitted", "committed", "failed"]) }),
]);
const pendingSchema = z.strictObject({ kind: z.literal("pending-list"), next: z.string().nullable(), items: z.array(z.object({
  id: z.string(), body: z.string(), digest: z.string(), reviewDigest: z.string(),
  change_kind: z.enum(["create", "replace", "retire"]), title: z.string(), actor: z.string(),
  sources: z.array(z.record(z.string(), z.unknown())), state: z.enum(["pending", "blocked"]),
  base_revision: z.string(), decision: z.string().nullable(), rejected_reason: z.string().nullable(),
})) });
const backupSchema = z.strictObject({ kind: z.literal("backup"), path: z.string(), manifestPath: z.string(), epoch: z.string(), sequence: z.number().int().nonnegative(), hash: z.string().regex(/^h:[a-f0-9]{64}$/), sizeBytes: z.number().int().positive() });
export type BackupReceipt = z.infer<typeof backupSchema>;
const restoreSchema = z.discriminatedUnion("success", [
  z.strictObject({ success: z.literal(true), path: z.string(), oldEpoch: z.string(), newEpoch: z.string(), restoredSequence: z.number().int().nonnegative(), retainedRevisions: z.number().int().nonnegative(), lostRevisions: z.null(), elapsedSeconds: z.number().nonnegative(), projects: z.array(z.strictObject({ project: z.string(), oldEpoch: z.string(), newEpoch: z.string(), sequence: z.number().int().nonnegative() })) }),
  z.strictObject({ success: z.literal(false), error: z.string() }),
]);
export type RestoreReceipt = z.infer<typeof restoreSchema>;

function failure(error: string, message: string): BridgeError { return { kind: "error", error, message }; }
function invoke<T>(operation: string, args: object, schema: z.ZodType<T>): T | BridgeError {
  let directory: string | undefined;
  try {
    directory = mkdtempSync(join(tmpdir(), "wiki-bridge-"));
    const argFile = join(directory, "request.json");
    writeFileSync(argFile, JSON.stringify({ operation, ...args }), { mode: 0o600 });
    const child = spawnSync("python3", [rpc, argFile], { encoding: "utf-8", timeout: 30000, maxBuffer: 16 * 1024 * 1024 });
    if (child.error) return failure("SubprocessError", child.error.message);
    if (child.status !== 0) {
      try {
        const error = errorSchema.safeParse(JSON.parse(child.stdout));
        if (error.success) return error.data;
      } catch { /* A failed interpreter need not emit JSON. */ }
      return failure("SubprocessError", `authority exited ${child.status ?? child.signal}: ${child.stderr.slice(-2000)}`);
    }
    const response: unknown = JSON.parse(child.stdout);
    const error = errorSchema.safeParse(response);
    if (error.success) return error.data;
    const parsed = schema.safeParse(response);
    return parsed.success ? parsed.data : failure("ProtocolError", parsed.error.message);
  } catch (error) {
    return failure("BridgeError", error instanceof Error ? error.message : String(error));
  } finally {
    if (directory) rmSync(directory, { recursive: true, force: true });
  }
}

export function connect(dbPath: string, project: string) {
  return invoke("connect", { database: dbPath, project }, connectionSchema);
}
export function createPage(dbPath: string, project: string, page: string, title: string, markdown: string, principal: string) {
  return invoke("create", { database: dbPath, project, page, title, markdown, principal }, pageSchema);
}
export function page(dbPath: string, project: string, page: string, revision?: string) {
  return invoke("wiki_page", { database: dbPath, project, args: { page, revision } }, pageSchema);
}
export function propose(dbPath: string, project: string, page: string, baseRevision: string,
  changeKind: "create" | "replace" | "retire", title: string, markdown: string, principal: string,
  sources: Record<string, unknown>[], key?: string) {
  return invoke("wiki_propose", { database: dbPath, project, principal, args: { page, baseRevision, changeKind, title, markdown, sources, key } }, proposalSchema.nullable());
}
export function decide(dbPath: string, project: string, proposalKey: string, decision: "publish" | "reject", digest?: string, reason?: string) {
  return invoke("wiki_curator_decide", { database: dbPath, project, principal: "curator", args: { proposalKey, decision, digest, reason } }, decisionSchema);
}
export function operation(dbPath: string, project: string, key: string, principal = "worker") {
  return invoke("wiki_operation", { database: dbPath, project, principal, args: { key } }, operationSchema);
}
export function pendingProposals(dbPath: string, project: string, limit = 20, cursor?: string) {
  if (!Number.isInteger(limit) || limit < 1 || limit > 100) return failure("InvalidInput", "limit must be 1..100");
  return invoke("wiki_curator_pending", { database: dbPath, project, principal: "curator", args: { limit, cursor } }, pendingSchema);
}
export function backupAuthority(store: ConnectedStore, directory: string) {
  const parsed = connectionSchema.safeParse(store);
  if (!parsed.success) return failure("InvalidInput", "backup requires a validated connection");
  return invoke("backup", { database: parsed.data.dbPath, project: parsed.data.project, directory }, backupSchema);
}
export function restoreAuthority(backupPath: string, targetDirectory: string): RestoreReceipt {
  const result = invoke("restore", { backupPath, targetDirectory }, restoreSchema);
  return "kind" in result ? { success: false, error: `${result.error}: ${result.message}` } : result;
}
export function verifyBoundary(dbPath?: string): boolean {
  const directory = dbPath ? undefined : mkdtempSync(join(tmpdir(), "wiki-boundary-"));
  try {
    const database = dbPath ?? join(directory ?? "", "authority.sqlite");
    const created = createPage(database, "verify", "boundary-page", "Boundary", "exact boundary body", "worker");
    if (created.kind !== "page") return false;
    const read = page(database, "verify", "boundary-page", created.revision);
    return read.kind === "page" && read.markdown === "exact boundary body" && read.hash === created.hash;
  } finally {
    if (directory) rmSync(directory, { recursive: true, force: true });
  }
}
