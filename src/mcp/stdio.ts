#!/usr/bin/env node
/** Local MCP stdio endpoint. OS process launch fixes identity and storage. */
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { ProtocolStdioServerTransport } from "./protocol-stdio.js";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import * as z from "zod/v4";
import { recall, recallInputSchema, closeQmdReaders, rerankerFromEnv } from "../retrieval/qmd-integration.js";

const [database, project, principal = "worker", mode, ...extra] = process.argv.slice(2);
if (!database || !project || extra.length || !["worker", "curator"].includes(principal)
    || (mode !== undefined && (mode !== "journaled" || principal !== "worker"))) {
  process.stderr.write("Usage: tsx src/mcp/stdio.ts DATABASE PROJECT [worker|curator] [journaled]\n");
  process.exit(2);
}
// journaled: the host adapter owns proposals through its durable call journal,
// so this server exposes no unjournaled mutation.
const journaled = mode === "journaled";
const db = resolve(database);
const rpc = fileURLToPath(new URL("./authority_rpc.py", import.meta.url));
const identifier = z.string().min(1).max(512);
const pageInput = z.strictObject({ page: identifier, revision: identifier.optional() });
const schemas = {
  wiki_page: pageInput,
  wiki_read: pageInput,
  wiki_recall: recallInputSchema,
  wiki_propose: z.strictObject({
    page: identifier, baseRevision: identifier,
    changeKind: z.enum(["replace", "retire"]), title: z.string().max(4096),
    markdown: z.string().max(1024 * 1024),
    sources: z.array(z.record(z.string(), z.unknown())).max(100).default([]),
    key: identifier.optional(),
  }),
  wiki_operation: z.strictObject({ key: identifier }),
  wiki_curator_pending: z.strictObject({ limit: z.number().int().min(1).max(100).default(20), cursor: z.string().min(1).max(4096).optional() }),
  wiki_curator_decide: z.strictObject({
    proposalKey: identifier, digest: identifier.optional(), decision: z.enum(["publish", "reject"]),
    reason: z.string().max(4096).optional(),
  }),
};
const server = new McpServer({ name: "project-wiki", version: "1.0.0" });
for (const [name, schema] of Object.entries(schemas)) {
  if (name.startsWith("wiki_curator_") && principal !== "curator") continue;
  if (journaled && name === "wiki_propose") continue;
  server.registerTool(name, {
    description: name === "wiki_curator_decide" ? "Decide after review. digest must be the current pending item's epoch-bound reviewDigest, not its payload digest."
      : `${name} in launch-bound project ${project}; principal ${principal}.`,
    inputSchema: schema,
  }, async (input: unknown): Promise<CallToolResult> => {
    // Parse strictly here as well as in SDK validation: identity overrides are never ignored.
    const args = schema.parse(input);
    try {
      if (name === "wiki_recall") {
        const parsed = schemas.wiki_recall.parse(args);
        const result = await recall({ database: db, project,
          indexRoot: process.env.WIKI_INDEX_ROOT ?? db + ".indexes", model: process.env.WIKI_QMD_MODEL, reranker: rerankerFromEnv() }, parsed);
        return { content: [{ type: "text", text: JSON.stringify(result) }] };
      }
      const text = execFileSync("python3", [rpc, db, project, principal, name], {
        input: JSON.stringify(args), encoding: "utf8", maxBuffer: 4 * 1024 * 1024,
        timeout: 30000, stdio: ["pipe", "pipe", "pipe"],
      }).trim();
      const result: unknown = JSON.parse(text);
      return { content: [{ type: "text", text: JSON.stringify(result) }] };
    } catch (error: unknown) {
      // Domain failures are tool failures, never fabricated success receipts.
      let text = "authority operation failed";
      if (error && typeof error === "object" && "stdout" in error && typeof error.stdout === "string") {
        text = error.stdout.trim() || text;
      }
      return { isError: true, content: [{ type: "text", text }] };
    }
  });
}
process.stdin.once("end", () => { void closeQmdReaders().catch(() => {}); });
await server.connect(new ProtocolStdioServerTransport());
