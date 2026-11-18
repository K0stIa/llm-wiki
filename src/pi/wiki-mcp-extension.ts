/** Session-local wiki binding. No saved configuration or access grants. */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { fileURLToPath } from "node:url";
import { journaledProposeTool, recoverJournal, type JournalBinding } from "./wiki-journal.js";

const identifier = Type.String({ minLength: 1, maxLength: 512 });
export const proposeSchema = Type.Object({
  page: identifier, baseRevision: identifier,
  changeKind: Type.Union([Type.Literal("replace"), Type.Literal("retire")]),
  title: Type.String({ maxLength: 4096 }), markdown: Type.String({ maxLength: 1024 * 1024 }),
  sources: Type.Optional(Type.Array(Type.Record(Type.String(), Type.Unknown()), { maxItems: 100 })),
}, { additionalProperties: false });

export default function wikiMcp(pi: ExtensionAPI) {
  const database = process.env.WIKI_DATABASE;
  const project = process.env.WIKI_PROJECT;
  if (!database || !project) throw new Error("WIKI_DATABASE and WIKI_PROJECT must be launch-bound");
  // WIKI_JOURNAL (trusted host storage, already enrolled) switches proposals to the
  // journaled native tool; the MCP server then exposes no unjournaled mutation.
  const journal = process.env.WIKI_JOURNAL;
  const binding: JournalBinding | undefined = journal ? { journal, database, project } : undefined;
  pi.registerMcpServer("wiki", {
    command: process.execPath,
    args: [fileURLToPath(new URL("../../node_modules/tsx/dist/cli.mjs", import.meta.url)),
      fileURLToPath(new URL("../mcp/stdio.ts", import.meta.url)), database, project, "worker",
      ...(binding ? ["journaled"] : [])],
    exposure: "direct",
    description: "Project-bound wiki read, lexical recall and durable proposals; no curator rights.",
  });
  if (binding) {
    const tool = journaledProposeTool(binding, proposeSchema);
    pi.registerTool({
      ...tool, parameters: proposeSchema,
      execute: (toolCallId, params, signal, onUpdate, ctx) => tool.execute(toolCallId, params, signal, onUpdate, ctx),
    });
  }
  let dispose: (() => void) | undefined;
  pi.on("session_start", async () => {
    // Finish calls interrupted by a crash before this session accepts new ones.
    if (binding) await recoverJournal(binding);
    const request: {
      version: 1;
      name: string;
      definition: {
        description: string; systemPrompt: string; tools: string[];
        mcpDirectTools: string[]; extensions: string[];
      };
      result?: { ok: true; registration: { dispose(): void } } | { ok: false; error: Error };
    } = {
      version: 1, name: "wiki-worker",
      definition: {
        description: "Worker with only project-bound wiki MCP tools. Run as a background child.",
        systemPrompt: "Use wiki MCP tools only. Cite page and revision. Never publish proposals.",
        // Runtime registrations use explicit MCP selectors; frontmatter's
        // mcp: shorthand is not parsed by the runtime registration API.
        tools: binding ? ["wiki_propose"] : [],
        mcpDirectTools: ["wiki/wiki_page", "wiki/wiki_recall", "wiki/wiki_operation",
          ...(binding ? [] : ["wiki/wiki_propose"])],
        extensions: [fileURLToPath(import.meta.url)],
      },
    };
    pi.events.emit("pi-subagents:runtime-agent-register:v1", request);
    if (request.result && !request.result.ok) throw request.result.error;
    if (request.result?.ok) dispose = () => {
      if (request.result?.ok) request.result.registration.dispose();
    };
  });
  pi.on("session_shutdown", async () => { dispose?.(); });
}
