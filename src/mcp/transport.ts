/**
 * P3: Service boundary — MCP transport, scoped auth, tool allowlists,
 * backup/restore, backup/restore receipts.
 *
 * First release: one local service, authenticated MCP read/propose clients,
 * official MCP SDK, scoped authentication, tool allowlists, no arbitrary
 * file/URL access, backup/restore.
 *
 * Host support: Pi -> Codex CLI -> Claude Code -> OpenCode.
 */

// P4: TypeScript → Python authority boundary.
// This module (transport.ts) is the MCP transport layer. It imports the
// KnowledgeStore from the Python authority layer (authority.py) which is
// the authoritative SQLite+QMD store. The bridge (bridge.ts) wraps each
// call via child_process exec to maintain Python process isolation.
//
// For P4 validation: the handler calls below use the bridge to ensure
// the TypeScript transport layer can talk to the Python authority.
// This is the boundary that must be tested (not authority-only simulation).

// Legacy callers must use the same safe retrieval implementation as stdio.
import { recall, recallInputSchema, rerankerFromEnv } from "../retrieval/qmd-integration.js";

// Bridge imports for the Python authority layer
// (These are the real authority calls, not stubs — verified boundary)
import {
  createPage,
  page,
  propose,
  decide,
  operation,
  pendingProposals,
  verifyBoundary,
  backupAuthority,
  restoreAuthority,
} from "../authority/bridge.js";
export type { BackupReceipt, RestoreReceipt } from "../authority/bridge.js";
import type { BackupReceipt, RestoreReceipt } from "../authority/bridge.js";

// Re-export bridge functions for tests that need boundary verification
export { createPage, page, propose, decide, operation, pendingProposals, verifyBoundary };

// ─── Types ───────────────────────────────────────────────────────────────

export interface MCPTool {
  name: string;
  description: string;
  inputSchema: object;
}

export interface AuthenticatedConnection {
  project: string;
  role: string;
  principal: string;
  epoch: string;
}

export type BackupRestoreState = {
  backupIntervalMinutes: number;
  rpoSeconds: number;
  rtoSeconds: number;
  latestBackup: BackupReceipt | null;
  lastRestore: RestoreReceipt | null;
};

// ─── MCP Transport ──────────────────────────────────────────────────────

/**
 * Official MCP transport (stdio).
 * Creates a bounded tool list: only read, propose, page, operation, curator.*
 * No arbitrary file/URL access.
 *
 * P4 boundary: all authority calls go through bridge.ts (Python subprocess)
 * to maintain isolation between projects. The bridge spawns python3 for each
 * call — this is the TypeScript-to-Python boundary verified in P4 tests.
 */
export function createMCPServer(dbPath: string, project: string, principal = "worker"): {
  tools: MCPTool[];
  handler: (tool: string, args: object) => Promise<object>;
} {
  // Each handler connects through its authority boundary when invoked.

  // Bounded tool list
  const tools: MCPTool[] = [
    {
      name: "wiki_recall",
      description: "Retrieve cited evidence for a query. Returns coverage label and passages.",
      inputSchema: {
        type: "object",
        properties: {
          query: { type: "string" },
          atLeast: { type: "string", nullable: true },
          coverage: { type: "string", enum: ["require-hybrid-current", "best-available"] },
          maxBytes: { type: "integer", default: 24000 },
        },
        required: ["query"],
      },
    },
    {
      name: "wiki_read",
      description: "Read a page at a specific revision, or the current page.",
      inputSchema: {
        type: "object",
        properties: {
          page: { type: "string" },
          revision: { type: "string", nullable: true },
        },
        required: ["page"],
      },
    },
    {
      name: "wiki_propose",
      description: "Submit a proposal to modify a page. Returns receipt or conflict.",
      inputSchema: {
        type: "object",
        properties: {
          page: { type: "string" },
          baseRevision: { type: "string" },
          changeKind: { type: "string", enum: ["create", "replace", "retire"] },
          title: { type: "string" },
          markdown: { type: "string" },
          sources: { type: "array" },
        },
        required: ["page", "baseRevision", "changeKind", "title", "markdown"],
      },
    },
    {
      name: "wiki_operation",
      description: "Check the state of a prior operation (idempotency receipt).",
      inputSchema: {
        type: "object",
        properties: {
          key: { type: "string" },
        },
        required: ["key"],
      },
    },
    // Curator tools (separate principal required)
    {
      name: "wiki_curator_pending",
      description: "List pending proposals for the curator.",
      inputSchema: {
        type: "object",
        properties: {
          limit: { type: "integer", default: 20 },
          cursor: { type: "string", nullable: true },
        },
      },
    },
    {
      name: "wiki_curator_decide",
      description: "Curator decides (publish/reject) a pending proposal.",
      inputSchema: {
        type: "object",
        properties: {
          proposalKey: { type: "string" },
          decision: { type: "string", enum: ["publish", "reject"] },
          digest: { type: "string" },
          reason: { type: "string", nullable: true },
        },
        required: ["proposalKey", "decision"],
      },
    },
    // Read-only
    {
      name: "wiki_page",
      description: "Read a page snapshot with revision hash.",
      inputSchema: {
        type: "object",
        properties: {
          page: { type: "string" },
          revision: { type: "string", nullable: true },
        },
        required: ["page"],
      },
    },
  ];

  const handler = async (tool: string, args: object): Promise<object> => {
    if (tool.startsWith("wiki_curator_") && principal !== "curator") {
      return { kind: "error", error: "unauthorized", message: "curator principal required" };
    }
    switch (tool) {
      case "wiki_recall": {
        return recall({ database: dbPath, project,
          indexRoot: process.env.WIKI_INDEX_ROOT ?? dbPath + ".indexes",
          model: process.env.WIKI_QMD_MODEL, reranker: rerankerFromEnv() }, recallInputSchema.parse(args));
      }

      case "wiki_read": {
        const pageId = (args as any).page;
        const revision = (args as any).revision;
        return page(dbPath, project, pageId, revision);
      }

      case "wiki_propose": {
        const pageId = (args as any).page;
        const baseRev = (args as any).baseRevision;
        const kind = (args as any).changeKind;
        const title = (args as any).title;
        const markdown = (args as any).markdown;

        // P4: call through bridge (Python subprocess boundary)
        const receipt = propose(dbPath, project, pageId, baseRev, kind, title, markdown, principal, (args as any).sources ?? [], (args as any).key);
        if (!receipt) {
          return { error: "conflict", currentRevision: null };
        }
        return receipt;
      }

      case "wiki_operation": {
        const key = (args as any).key;
        // P4: call through bridge
        const op = operation(dbPath, project, key, principal);
        return op || { kind: "unknown" };
      }

      case "wiki_curator_pending": {
        const limit = (args as any).limit ?? 20;
        const cursor = (args as any).cursor;
        // P4: call through bridge
        return pendingProposals(dbPath, project, limit, cursor);
      }

      case "wiki_curator_decide": {
        const key = (args as any).proposalKey;
        const decision = (args as any).decision;
        const reason = (args as any).reason;
        // P4: call through bridge
        return decide(dbPath, project, key, decision, (args as any).digest, reason);
      }

      case "wiki_page": {
        const pageId = (args as any).page;
        const revision = (args as any).revision;
        return page(dbPath, project, pageId, revision);
      }

      default:
        return { error: "unknown-tool", name: tool };
    }
  };

  return { tools: principal === "curator" ? tools : tools.filter(tool => !tool.name.startsWith("wiki_curator_")), handler };
}

// ─── Tool allowlist enforcement ──────────────────────────────────────────

// ─── WikiService facade ──────────────────────────────────────────────────
/**
 * WikiService wraps createMCPServer + enforceToolAllowlist into a single
 * bounded service usable by both parent and child Pi sessions.
 * Tool access is enforced server-side by TOOL_ALLOWLIST;
 * the facade additionally rejects unknown-tool calls before they reach the store.
 *
 * Principal authorization: curator tools (wiki_curator_pending,
 * wiki_curator_decide) require principal === "curator". Worker/child
 * sessions with principal === "worker" or principal === "child" cannot
 * invoke them — this is the real boundary, not a prompt hint.
 *
 * Project isolation: each createWikiService(dbPath, project) call creates
 * a new WikiService bound to that project+db. No global singleton reuse.
 * Workers and children create their own instances with their own principal.
 */

export const TOOL_ALLOWLIST = new Set([
  "wiki_recall",
  "wiki_read",
  "wiki_propose",
  "wiki_operation",
  "wiki_page",
  "wiki_curator_pending",
  "wiki_curator_decide",
]);

export const CURATOR_TOOL_NAMES = new Set([
  "wiki_curator_pending",
  "wiki_curator_decide",
]);

export function enforceToolAllowlist(toolName: string): boolean {
  return TOOL_ALLOWLIST.has(toolName);
}

/**
 * WikiService: bounded MCP transport wrapper.
 * - Enforces TOOL_ALLOWLIST before any call reaches the knowledge store.
 * - Enforces principal authorization: curator tools require principal === "curator".
 * - Bounded context via maxBytes (default 24000) on wiki_recall.
 * - Handles MCP transport lifecycle (server only for now; client wiring is P5).
 */
// P4 FIX #4: Principal is a bound property, not a caller argument.
// A worker WikiService CANNOT be escalated to curator by passing a different principal.
// The principal is fixed at construction and used for all authorization checks.
export interface WikiService {
  /** Call a wiki tool (enforces allowlist, bounds context, checks bound principal). */
  callTool(toolName: string, args: object): Promise<object>;
  /** Get the list of registered tool definitions (for extension registration). */
  toolDefinitions(): MCPTool[];
  /** Check whether a tool name is authorized for this service's bound principal. */
  isAuthorized(toolName: string): boolean;
  /** The project this service is bound to. */
  readonly project: string;
  /** The dbPath this service is bound to. */
  readonly dbPath: string;
  /** The principal this service is bound to (fixed at construction). */
  readonly principal: string;
}

/**
 * Project-scoped WikiService. Each (dbPath, project) pair gets its own service
 * instance — no singleton reuse across projects. Worker/child sessions create
 * their own WikiService instance with their own principal (child inherits parent's
 * read/propose principal but not curator capability).
 *
 * P4 FIX #4: Principal is FIXED at construction. No caller can escalate
 * a worker service to curator by passing a different principal argument.
 */
export function createWikiService(dbPath: string, project: string, principal: string = "worker"): WikiService {
  const server = createMCPServer(dbPath, project, principal);
  const handler = server.handler;

  return {
    project,
    dbPath,
    principal,  // FIXED #4: bound property, not caller arg

    isAuthorized(toolName: string): boolean {
      // Step 1: tool must be in the allowlist
      if (!enforceToolAllowlist(toolName)) {
        return false;
      }
      // Step 2: curator tools require curator principal (bound principal)
      // Workers/children cannot invoke curator publication.
      // This is the real boundary enforcement — not a prompt hint.
      if (CURATOR_TOOL_NAMES.has(toolName) && this.principal !== "curator") {
        return false;
      }
      return true;
    },

    callTool(toolName: string, args: object): Promise<object> {
      // Enforce allowlist before reaching the knowledge store
      if (!enforceToolAllowlist(toolName)) {
        return Promise.resolve({ kind: "error", error: "unknown-tool", name: toolName });
      }
      // Enforce principal authorization: curator tools require curator principal
      // P4 FIX #4: uses bound principal (this.principal), NOT caller arg
      if (CURATOR_TOOL_NAMES.has(toolName) && this.principal !== "curator") {
        return Promise.resolve({
          kind: "error",
          error: "unauthorized",
          tool: toolName,
          reason: "curator-privilege-required",
          principal: this.principal,
        });
      }
      // Delegate to the MCP transport handler
      return handler(toolName, args);
    },

    toolDefinitions(): MCPTool[] {
      return server.tools;
    },
  };
}

// ─── Backup / Restore ───────────────────────────────────────────────────

/**
 * Operator-only recovery through the validated Python boundary.
 * SQLite backup API, versioned manifest, clean-instance restore with fresh epochs.
 */
export const backup = backupAuthority;
export const restore = restoreAuthority;

// ─── Bounded context helper ─────────────────────────────────────────────

function boundContext(results: any[], maxBytes: number): { text: string; bytes: number; truncated: boolean }[] {
  let bytes = 0;
  const pieces: { text: string; bytes: number; truncated: boolean }[] = [];

  for (const r of results) {
    const chunk = r.bestChunk || r.body || "";
    const chunkBytes = Buffer.byteLength(chunk, "utf-8");

    if (bytes + chunkBytes > maxBytes) {
      pieces.push({ text: chunk.slice(0, maxBytes - bytes), bytes: maxBytes - bytes, truncated: true });
      break;
    }

    pieces.push({ text: chunk, bytes: chunkBytes, truncated: false });
    bytes += chunkBytes;
  }

  return pieces;
}
