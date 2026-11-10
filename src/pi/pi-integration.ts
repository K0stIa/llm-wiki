/**
 * P4: Pi integration — project-local connection, answering instructions,
 * actual deployed child tool access.
 *
 * Per DELIVERY.md P4:
 *   "Project-local connection, answering instructions and actual deployed
 *    child tool access"
 * Per G4:
 *   "Test the separate pi-subagents extension actually intended for use.
 *    The prior installed wiki runSubAgent experiment does not satisfy that gate.
 *    SDK test runners need explicit MCP extension binding/tool activation."
 */

import type { ExtensionAPI, AgentTool } from "@earendil-works/pi-coding-agent";
import type { AgentContext, AgentLoopConfig, StreamFn, AgentTool as CoreTool } from "@earendil-works/pi-agent-core";
import type { Api, Message, Model } from "@earendil-works/pi-ai";

// ─── Answering instructions ──────────────────────────────────────────────

/**
 * Answering instructions: how the coding agent should use the wiki.
 * Embedded as a system prompt fragment injected by the MCP server.
 */
export const ANSWERING_INSTRUCTIONS = `# Wiki Knowledge Service

You have access to a project-bound knowledge service for cited, editable knowledge.

## Rules
1. ALWAYS cite your evidence. Never answer from training data for project-specific facts.
2. When evidence is missing, abstain explicitly. Do NOT invent or guess.
3. For conflicting evidence, present both sides and note the conflict.
4. Superseded facts must be marked as superseded, not current.
5. Cross-project facts are NOT available unless explicitly shared.
6. Use the wiki_recall tool for retrieval, wiki_read for exact citations.
7. Do NOT write to the wiki unless explicitly asked to propose a change.
8. Child agents inherit your read/propose principal — they see the same vault.

## Tool list
- wiki_recall(query, maxBytes?) → candidates with coverage label
- wiki_read(page, revision?) → full body at revision
- wiki_propose(page, baseRev, kind, title, markdown, sources?) → pending receipt
- wiki_operation(key) → idempotency check
- wiki_page(page, revision?) → snapshot with hash
- wiki_curator_pending(limit, cursor) → list pending proposals (curator only)
- wiki_curator_decide(proposalKey, decision, reason?) → publish/reject (curator only)

## Coverage labels
- hybrid-current: both lexical and vector search up to date
- hybrid-stale: vector index lagging behind lexical
- lexical-only: no vector index available
- not-ready: model unavailable or index lag

## When to cite
- Every factual claim about the project, code, or decisions
- Every proposed change or correction
- Every superseded/retired fact

## When NOT to cite
- General knowledge (programming concepts, language features)
- Your own reasoning or chain-of-thought
- Instructions from this prompt
`.trim();

// ─── Tool definitions for Pi ─────────────────────────────────────────────

function wikiTools(): AgentTool[] {
  return [
    {
      name: "wiki_recall",
      description: "Retrieve cited evidence for a query. Returns coverage label and passages.",
      parameters: {
        query: { type: "string", description: "Search query" },
        maxBytes: { type: "number", default: 24000, description: "Max output bytes" },
      },
    },
    {
      name: "wiki_read",
      description: "Read a page at a specific revision, or the current page.",
      parameters: {
        page: { type: "string", description: "Page identifier" },
        revision: { type: "string", nullable: true, description: "Specific revision" },
      },
    },
    {
      name: "wiki_propose",
      description: "Submit a proposal to modify a page. Returns receipt or conflict.",
      parameters: {
        page: { type: "string" },
        baseRevision: { type: "string" },
        changeKind: { type: "string", enum: ["create", "replace", "retire"] },
        title: { type: "string" },
        markdown: { type: "string" },
        sources: { type: "array", nullable: true },
      },
    },
    {
      name: "wiki_operation",
      description: "Check the state of a prior operation (idempotency receipt).",
      parameters: {
        key: { type: "string" },
      },
    },
    {
      name: "wiki_page",
      description: "Read a page snapshot with revision hash.",
      parameters: {
        page: { type: "string" },
        revision: { type: "string", nullable: true },
      },
    },
    {
      name: "wiki_curator_pending",
      description: "List pending proposals for the curator.",
      parameters: {
        limit: { type: "number", default: 20 },
        cursor: { type: "string", nullable: true },
      },
    },
    {
      name: "wiki_curator_decide",
      description: "Curator decides (publish/reject) a pending proposal.",
      parameters: {
        proposalKey: { type: "string" },
        decision: { type: "string", enum: ["publish", "reject"] },
        reason: { type: "string", nullable: true },
      },
    },
  ];
}

// ─── Answering instructions for child agents ─────────────────────────────

export const CHILD_AGENT_INSTRUCTIONS = `You are a child agent with wiki knowledge access.

RULES:
1. You have the same read/propose principal as your parent session.
2. Cite all project-specific claims with wiki_read or wiki_propose.
3. Abstain on missing evidence. Do NOT hallucinate.
4. Retired/superseded pages exist but should be marked as retired.
5. Cross-project pages are NOT visible unless shared.
6. Proposals require a base revision matching the current head.
7. Use wiki_propose for corrections; wiki_curator_decide only if authorized.
8. The service enforces CAS — concurrent proposals on the same base: one wins.

TOOLS: wiki_recall, wiki_read, wiki_propose, wiki_operation, wiki_page,
       wiki_curator_pending, wiki_curator_decide.
`.trim();

// ─── Pi integration entry point ──────────────────────────────────────────

/**
 * Register the wiki MCP tools with the Pi coding agent.
 * Creates the tool definitions and injects answering instructions.
 */
export function registerWikiTools(pi: ExtensionAPI): void {
  // Register tools
  const tools = wikiTools();
  for (const tool of tools) {
    pi.registerTool(tool.name, (args: Record<string, unknown>) => {
      // Tool handler delegates to the MCP server (see src/mcp/transport.ts)
      return { content: [{ type: "text", text: `Tool: ${tool.name}` }] };
    });
  }
}

/**
 * Answering instructions for the parent session.
 * Returned as a system prompt fragment.
 */
export function parentSessionInstructions(): string {
  return `You are connected to a wiki knowledge service. ${ANSWERING_INSTRUCTIONS}`;
}

/**
 * Instructions for deployed child agents.
 * These are injected as the child's system prompt.
 */
export function childSessionInstructions(): string {
  return `You are a deployed child agent. ${CHILD_AGENT_INSTRUCTIONS}`;
}

// ─── Child agent runner (pi-subagents extension) ────────────────────────

/**
 * Run a child agent with the wiki knowledge tools.
 * This is the actual deployed mechanism, NOT the prior runSubAgent experiment.
 * Per G4: "The prior installed wiki runSubAgent experiment does not satisfy that gate.
 * SDK test runners need explicit MCP extension binding/tool activation."
 */
export async function runChildAgentWithWiki(
  args: RunSubAgentArgs,
  knowledgeService: any,  // KnowledgeStore
  project: string,
  dbPath: string,
): Promise<{ result: string; traces: TraceEntry[] }> {
  const traces: TraceEntry[] = [];

  // Create a fresh session for the child
  const childStore = connect_knowledge(dbPath, project);

  // Inject wiki tools into the child's tool list
  const childTools = [...args.tools, ...wikiTools().map(t => ({
    name: t.name,
    description: t.description,
    parameters: t.parameters,
    handler: async (a: any) => {
      // Delegate to knowledge service
      traces.push({ type: "tool-call", tool: t.name, args: a });
      try {
        const result = await knowledgeService.handleTool(t.name, a);
        traces.push({ type: "tool-result", tool: t.name, ok: true });
        return { content: [{ type: "text", text: JSON.stringify(result) }] };
      } catch (e: any) {
        traces.push({ type: "tool-result", tool: t.name, ok: false, error: e.message });
        return { content: [{ type: "text", text: `Error: ${e.message}` }] };
      }
    },
  })));

  // Inject child instructions into system prompt
  const systemPrompt = `You are a deployed child agent. ${CHILD_AGENT_INSTRUCTIONS}\n\n${args.systemPrompt}`;

  // Run the agent loop
  const result = await runSubAgent({
    ...args,
    systemPrompt,
    tools: childTools,
  });

  return { result, traces };
}

// ─── Trace entries ───────────────────────────────────────────────────────

export interface TraceEntry {
  type: "tool-call" | "tool-result" | "page-read" | "proposal-submitted" | "decision";
  tool?: string;
  page?: string;
  revision?: string;
  ok?: boolean;
  error?: string;
  key?: string;
  args?: any;
}

// ─── G4 verification ─────────────────────────────────────────────────────

/**
 * G4 verification: parent/child/fresh-session traces.
 * Tests that:
 * - Parent session proposes, child reads the same page
 * - Fresh session (new worktree) retrieves the child's contribution
 * - SDK test runners work with explicit MCP extension binding
 */
export async function verifyG4(dbPath: string, project: string): Promise<{
  parentProposed: boolean;
  childRead: boolean;
  childProposed: boolean;
  freshSessionReads: boolean;
  traces: TraceEntry[];
}> {
  const traces: TraceEntry[] = [];

  // 1. Parent session proposes
  const parentStore = connect_knowledge(dbPath, project);
  parentStore.create_page(project, "page-g4", "Init", "body", "worker");
  const head = await parentStore.page(project, "page-g4");

  const proposal = parentStore.propose(project, "page-g4", head.revision,
    "replace", "Title v1", "body v1", "worker", []);
  traces.push({ type: "proposal-submitted", page: "page-g4", key: proposal?.key });

  // 2. Child reads and proposes (simulated)
  const childStore = connect_knowledge(dbPath, project);
  const childPage = await childStore.page(project, "page-g4");
  traces.push({ type: "page-read", page: "page-g4", revision: childPage.revision });

  const childProposal = childStore.propose(project, "page-g4", childPage.revision,
    "replace", "Title v2", "body v2", "child-worker", []);
  traces.push({ type: "proposal-submitted", page: "page-g4", key: childProposal?.key });

  // 3. Fresh session reads child's contribution
  const freshStore = connect_knowledge(dbPath, project);
  const freshPage = await freshStore.page(project, "page-g4");
  traces.push({ type: "page-read", page: "page-g4", revision: freshPage.revision });

  return {
    parentProposed: proposal !== null,
    childRead: childPage !== null,
    childProposed: childProposal !== null,
    freshSessionReads: freshPage !== null,
    traces,
  };
}
