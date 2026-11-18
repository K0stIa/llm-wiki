/**
 * Trusted host adapter for journaled wiki proposals (G1 host-call journal).
 *
 * The durable call identity is the host's own: (session id, tool call id) as
 * persisted by the host session. It never comes from model arguments. The
 * Python journal commits the derived key and the exact request BEFORE sending,
 * so a crash after the authority committed but before the receipt was recorded
 * is recovered by replaying the same key, never by minting a new one.
 */
import { execFile } from "node:child_process";
import { fileURLToPath } from "node:url";

export interface JournalBinding {
  /** Journal file in trusted host storage, outside every worker mount. */
  journal: string;
  database: string;
  project: string;
}

export interface ProposeArgs {
  page: string;
  baseRevision: string;
  changeKind: "replace" | "retire";
  title: string;
  markdown: string;
  sources?: Record<string, unknown>[];
}

const script = fileURLToPath(new URL("../mcp/journal_rpc.py", import.meta.url));
const FORBIDDEN = ["key", "expectedEpoch"];

function call(binding: JournalBinding, request: object): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    const child = execFile("python3", [script, binding.journal, binding.database, binding.project],
      { encoding: "utf8", maxBuffer: 4 * 1024 * 1024, timeout: 120_000 },
      (error, stdout) => {
        let reply: unknown;
        try { reply = JSON.parse(stdout.trim()); } catch { reply = undefined; }
        if (!error && reply && typeof reply === "object") return resolve(reply as Record<string, unknown>);
        // A crash leaves no reply. Never report success; the caller must recover.
        const message = reply && typeof reply === "object" && "message" in reply ? String(reply.message)
          : `journal adapter exited without a reply (${error?.code ?? "no exit code"})`;
        reject(new Error(message));
      });
    child.stdin?.end(JSON.stringify(request));
  });
}

export function identity(value: unknown, what: string): string {
  if (typeof value !== "string" || !value || value.length > 512 || value.includes("\0")) {
    throw new Error(`durable ${what} identity unavailable; journaled mutation refused`);
  }
  return value;
}

export async function journaledPropose(binding: JournalBinding, session: string, toolCallId: string,
  args: ProposeArgs): Promise<unknown> {
  if (FORBIDDEN.some((name) => Object.hasOwn(args, name))) throw new Error("key/expectedEpoch are host-derived");
  const reply = await call(binding, {
    op: "execute", session: identity(session, "session"), call: identity(toolCallId, "tool call"),
    args: { ...args, sources: args.sources ?? [] },
  });
  return reply.result;
}

/** Replay unfinished journaled calls. Run before accepting new calls after any restart. */
export async function recoverJournal(binding: JournalBinding): Promise<unknown[]> {
  const reply = await call(binding, { op: "recover" });
  return reply.calls as unknown[];
}

export async function enrollJournal(binding: JournalBinding): Promise<unknown> {
  return call(binding, { op: "enroll" });
}

/** Minimal slice of Pi's ExtensionToolContext that the tool relies on. */
export interface SessionContext {
  sessionManager: { getSessionId(): string };
}

/**
 * Pi native tool replacing the MCP wiki_propose when a journal is configured.
 * Identity: ctx.sessionManager.getSessionId() + Pi's toolCallId.
 */
export function journaledProposeTool(binding: JournalBinding, schema: unknown) {
  return {
    name: "wiki_propose",
    label: "Wiki propose",
    description: `Propose a full replacement or retirement of a page in project ${binding.project}. ` +
      "Pending until a curator reviews it. Journaled: a lost reply is recovered, never resubmitted under a new key.",
    parameters: schema,
    async execute(toolCallId: string, params: ProposeArgs, _signal: unknown, _onUpdate: unknown,
      ctx: SessionContext) {
      const result = await journaledPropose(binding, ctx.sessionManager.getSessionId(), toolCallId, params);
      return { content: [{ type: "text" as const, text: JSON.stringify(result) }], details: result };
    },
  };
}
