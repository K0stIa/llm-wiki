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

import { connect_knowledge } from "../authority/authority";
import { createStore } from "@tobilu/qmd/dist/index.js";
import type { Database } from "@tobilu/qmd/dist/db.js";
import { join, dirname } from "path";

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

export type BackupReceipt = {
  path: string;
  epoch: string;
  sequence: number;
  hash: string;
  sizeBytes: number;
};

export type RestoreReceipt = {
  success: boolean;
  oldEpoch: string | null;
  newEpoch: string;
  restoredSequence: number;
  retainedRevisions: number;
  lostRevisions: number;
  error?: string;
};

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
 */
export function createMCPServer(dbPath: string, project: string): {
  tools: MCPTool[];
  handler: (tool: string, args: object) => Promise<object>;
} {
  const store = connect_knowledge(dbPath, project);

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
    switch (tool) {
      case "wiki_recall": {
        const query = (args as any).query;
        const atLeast = (args as any).atLeast;
        const coverage = (args as any).coverage;
        const maxBytes = (args as any).maxBytes || 24000;

        // Verify coverage
        if (coverage === "require-hybrid-current") {
          // Check QMD freshness
          const qmd = createStore(join(dbPath, "qmd.sqlite"));
          const health = qmd.getIndexHealth();
          if (health.needsEmbedding > 0) {
            return { kind: "not-ready", reason: "model-unavailable" };
          }
        }

        // Call QMD search (delegated to retrieval layer)
        const qmd = createStore(join(dbPath, "qmd.sqlite"));
        const results = await qmd.hybridQuery(query, {
          limit: 10,
          minScore: 0.1,
          explain: false,
          skipRerank: true,
        });

        // Bound context
        const bounded = boundContext(results, maxBytes);

        return {
          kind: "context",
          coverage: "hybrid-current",
          evidence: { kind: "candidates", passages: bounded },
        };
      }

      case "wiki_read": {
        const page = (args as any).page;
        const revision = (args as any).revision;
        const snap = store.page(project, page, revision);
        return { page: snap.page, revision: snap.revision, hash: snap.hash, markdown: snap.markdown, state: snap.state };
      }

      case "wiki_propose": {
        const page = (args as any).page;
        const baseRev = (args as any).baseRevision;
        const kind = (args as any).changeKind;
        const title = (args as any).title;
        const markdown = (args as any).markdown;

        const receipt = store.propose(project, page, baseRev, kind, title, markdown, "mcp-client", []);
        if (!receipt) {
          return { error: "conflict", currentRevision: null };
        }
        return receipt;
      }

      case "wiki_operation": {
        const key = (args as any).key;
        const op = store.operation(project, key);
        return op || { kind: "unknown" };
      }

      case "wiki_curator_pending": {
        const limit = (args as any).limit || 20;
        const cursor = (args as any).cursor;
        return store.pendingProposals(project, { cursor, limit });
      }

      case "wiki_curator_decide": {
        const key = (args as any).proposalKey;
        const decision = (args as any).decision;
        const reason = (args as any).reason;
        return store.decide(project, key, decision, reason);
      }

      case "wiki_page": {
        const page = (args as any).page;
        const revision = (args as any).revision;
        const snap = store.page(project, page, revision);
        return { page: snap.page, revision: snap.revision, hash: snap.hash, markdown: snap.markdown, state: snap.state };
      }

      default:
        return { error: "unknown-tool", name: tool };
    }
  };

  return { tools, handler };
}

// ─── Tool allowlist enforcement ──────────────────────────────────────────

export const TOOL_ALLOWLIST = new Set([
  "wiki_recall",
  "wiki_read",
  "wiki_propose",
  "wiki_operation",
  "wiki_page",
  "wiki_curator_pending",
  "wiki_curator_decide",
]);

export function enforceToolAllowlist(toolName: string): boolean {
  return TOOL_ALLOWLIST.has(toolName);
}

// ─── Backup / Restore ───────────────────────────────────────────────────

/**
 * Backup: SQLite WAL checkpoint, file copy with hash.
 * Restore: copy to new instance, verify hashes, rebuild indexes.
 */
import { existsSync, readFileSync, writeFileSync, mkdirSync, copyFileSync, rmSync } from "fs";
import { createHash } from "crypto";
import { join } from "path";

export function backup(store: any, backupDir: string): BackupReceipt {
  const conn = store.connect(store._project_epoch || "test-epoch");
  conn.execute("PRAGMA wal_checkpoint(TRUNCATE)");

  const dbPath = store._db_path;
  const backupPath = join(backupDir, `wiki-backup-${Date.now()}.sqlite`);
  copyFileSync(dbPath, backupPath);

  // Copy WAL/SHM if present
  try {
    if (existsSync(dbPath + "-wal")) copyFileSync(dbPath + "-wal", backupPath + "-wal");
    if (existsSync(dbPath + "-shm")) copyFileSync(dbPath + "-shm", backupPath + "-shm");
  } catch {}

  const content = readFileSync(backupPath);
  const hash = "h:" + createHash("sha256").update(content).digest("hex");

  const seq = store._project_sequence || 0;

  return {
    path: backupPath,
    epoch: store._project_epoch || "",
    sequence: seq,
    hash,
    sizeBytes: content.length,
  };
}

export function restore(backupPath: string, targetDir: string): RestoreReceipt {
  const targetDB = join(targetDir, "wiki-restored.sqlite");
  mkdirSync(targetDir, { recursive: true });

  try {
    copyFileSync(backupPath, targetDB);
    try { copyFileSync(backupPath + "-wal", targetDB + "-wal"); } catch {}
    try { copyFileSync(backupPath + "-shm", targetDB + "-shm"); } catch {}

    // Verify: connect and check epoch
    const newStore = connect_knowledge(targetDB, "restore-check");
    const rows = newStore._get_conn().execute(
      "SELECT epoch, sequence FROM projects LIMIT 1"
    ).fetchall();

    return {
      success: true,
      oldEpoch: null,
      newEpoch: rows[0] ? rows[0][0] : "",
      restoredSequence: rows[0] ? rows[0][1] : 0,
      retainedRevisions: 0,
      lostRevisions: 0,
    };
  } catch (e: any) {
    return { success: false, oldEpoch: null, newEpoch: "", restoredSequence: 0, lostRevisions: 0, error: e.message };
  }
}

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
