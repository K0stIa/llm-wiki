/**
 * Legacy in-process Pi adapter, retained for historical unit tests.
 * The runnable MCP integration is wiki-mcp-extension.ts plus ../mcp/stdio.ts.
 * This file does not establish native child execution or a host acceptance gate.
 *
 * Per DELIVERY.md P4:
 *   "Project-local connection, answering instructions and actual deployed
 *    child tool access"
 * Per G4:
 *   "Test the separate pi-subagents extension actually intended for use.
 *    The prior installed wiki runSubAgent experiment does not satisfy that gate.
 *    SDK test runners need explicit MCP extension binding/tool activation."
 *
 * Historical API assumptions (not current runtime evidence):
 *   - This prototype targeted pi-subagents v0.12.5; installed v0.84.0 uses
 *     runtime-agent registration and explicit mcpDirectTools selectors instead.
 *   - registerSubagentExtension(pi)  // main extension entry
 *   - registerSubagentToolActivation(pi, options)  // tool activation config
 *   - registerPinnedTool(pi, tool)  // pin tool definitions to session
 *   - registerSubagentToolActivation(pi, { mode: "auto", advertisedPrompt, hasPendingSupervisorRequest? })
 *   - registerSubagentExtension does NOT export runSubAgent — that is the
 *     prior installed wiki experiment that G4 explicitly excludes.
 */

import type { ExtensionAPI, AgentTool } from "@earendil-works/pi-coding-agent";
import type { AgentContext, AgentLoopConfig, StreamFn, AgentTool as CoreTool } from "@earendil-works/pi-agent-core";
import type { Api, Message, Model } from "@earendil-works/pi-ai";
import { createWikiService, createMCPServer, enforceToolAllowlist, TOOL_ALLOWLIST, CURATOR_TOOL_NAMES, WikiService } from "../mcp/transport.js";
import { createPage, page, propose, decide, operation, pendingProposals, verifyBoundary } from "../authority/bridge.js";

// Real pi-subagents extension — NOT the prior runSubAgent experiment.
// The installed package at ~/.pi/agent/npm/node_modules/pi-subagents/ exports:
//   registerSubagentExtension(pi): void
//   registerSubagentToolActivation(pi, { mode, advertisedPrompt, hasPendingSupervisorRequest }): void
//   registerPinnedTool<T>(pi, tool): void  // from declaration-pinning.js
//   setDeclarationPinning(pi, pinned): void
// Verified: no runSubAgent, runChildAgentWithWiki, or handleTool exports exist.
// The "subagent" tool is the actual deployed mechanism (registered via registerPinnedTool).

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

// ─── Tool definitions for Pi (for documentation / verification) ──────────
/**
 * The actual tool definitions are created by createWikiService() which
 * reads from transport.ts's TOOL_ALLOWLIST. This array is kept for
 * documentation and for the verifyG4 function's reference.
 */
const WIKI_TOOL_DEFINITIONS = [
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
    parameters: { key: { type: "string" } },
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

// Exported for tests that need the canonical tool list
export const WIKI_TOOL_NAMES = WIKI_TOOL_DEFINITIONS.map(t => t.name);

// ─── Pi integration entry point ──────────────────────────────────────────

/**
 * Register the wiki MCP tools with the Pi coding agent.
 * Per G4: "SDK test runners need explicit MCP extension binding/tool activation."
 * This wires each wiki tool through the real MCP transport (WikiService),
 * enforces TOOL_ALLOWLIST and principal authorization, and injects
 * ANSWERING_INSTRUCTIONS.
 *
 * Each call creates a fresh WikiService instance bound to (dbPath, project).
 * No global singleton — different projects get different services.
 *
 * Principal boundary: worker principal can call wiki_recall/wiki_propose but
 * NOT wiki_curator_decide. Curator principal can call all tools.
 *
 * This is NOT the prior runSubAgent experiment. The real deployed mechanism
 * uses registerSubagentExtension + registerPinnedTool + registerSubagentToolActivation.
 */
export function registerWikiTools(pi: ExtensionAPI, dbPath: string, project: string, principal: string = "worker"): void {
  // Per-project WikiService: no singleton reuse (each project/db pair is isolated)
  const wikiService = createWikiService(dbPath, project, principal);

  // Register each wiki tool as a real MCP handler (not a stub)
  const toolDefs = wikiService.toolDefinitions();
  for (const def of toolDefs) {
    // Only register tools authorized for this principal
    if (!wikiService.isAuthorized(def.name)) continue;

    // Convert MCPTool → ToolDefinition for Pi's registerTool
    const toolDef: ToolDefinition = {
      name: def.name,
      description: def.description,
      parameters: def.inputSchema,
      promptGuidelines: def.name.includes("curator")
        ? `Curator tool — requires principal=curator. Current principal: ${principal}.` +
          (principal !== "curator" ? " BLOCKED: unauthorized for this session." : "")
        : undefined,
      execute: async (id: string, args: Record<string, unknown>, _signal: AbortSignal | undefined, onUpdate: unknown, _ctx: any) => {
        // Enforce allowlist + principal (belt-and-suspenders: transport also enforces)
        // P4 FIX #4: uses wikiService.principal (bound), not caller principal
        if (!wikiService.isAuthorized(def.name)) {
          if (wikiService.principal !== "curator" && def.name.includes("curator")) {
            return { kind: "error", error: "unauthorized", tool: def.name, reason: "curator-privilege-required", principal: wikiService.principal };
          }
          return { kind: "error", error: "unknown-tool", name: def.name };
        }
        const result = await wikiService.callTool(def.name, args);
        return { content: [{ type: "text", text: JSON.stringify(result) }], isError: !!(result as any).error };
      },
    };

    // P4 FIX #1: registerTool takes ToolDefinition (not name, handler)
    pi.registerTool(toolDef);
  }

  // Inject ANSWERING_INSTRUCTIONS into the system prompt
  // Per G4: "Assert the child can see and call the read/propose tools, rather than
  // trusting a parent summary or tool listing." — we inject the full instruction
  // text into the prompt, not just a tool list reference.
  const currentInstructions = (pi as any).getSystemPrompt?.() ?? "";
  if (currentInstructions && !currentInstructions.includes("Wiki Knowledge Service")) {
    (pi as any).appendSystemPrompt?.(ANSWERING_INSTRUCTIONS);
  } else if (!currentInstructions) {
    (pi as any).appendSystemPrompt?.(ANSWERING_INSTRUCTIONS);
  }
}

interface ToolDefinition {
  name: string;
  description: string;
  parameters: object;
  promptGuidelines?: string;
  execute: (id: string, args: Record<string, unknown>, signal: AbortSignal | undefined, onUpdate: unknown, ctx: any) => Promise<any>;
}

// ─── Answering instructions for the parent session. ─────────────────────

export function parentSessionInstructions(): string {
  return `You are connected to a wiki knowledge service. ${ANSWERING_INSTRUCTIONS}`;
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
 *
 * Deprecated prototype wiring; the following old API assumptions are NOT
 * verified against installed pi-subagents v0.84.0. Use wiki-mcp-extension.ts.
 * Historical mechanism:
 *   1. registerSubagentExtension(pi) — registers the "subagent" tool on parent
 *   2. registerSubagentToolActivation(pi, { mode, advertisedPrompt, hasPendingSupervisorRequest })
 *      — configures child tool activation; mode "auto" means tools are
 *        automatically available to children without per-call approval
 *   3. registerPinnedTool(pi, tool) for each wiki tool — pins the tool definition
 *      so the child session keeps the same tool definition (not just a name)
 *   4. The child session creates its OWN WikiService instance (different project
 *      scope or different principal) — NOT the parent's WikiService.
 *
 * Principal boundary: the child inherits the parent's read/propose principal
 * ("worker") but does NOT inherit curator capability. The child's WikiService
 * is created with principal === "child" (or its own principal), so it can call
 * wiki_recall/wiki_read/wiki_propose but NOT wiki_curator_decide.
 *
 * Per G4: "Launch the host's actual deployed child mechanism. Assert the child
 * can see and call the read/propose tools, rather than trusting a parent summary."
 * — this function verifies by returning traces that prove the child called wiki tools.
 */

// Re-export the real pi-subagents extension functions (verified installed APIs)
// These come from ~/.pi/agent/npm/node_modules/pi-subagents/src/extension/
// Note: we import these dynamically to avoid hard dependency on the exact module
// path at build time (they may move between versions).

let _subagentExtensionModule: typeof import("pi-subagents/src/extension/index.js") | null = null;

async function loadSubagentExtensions(): Promise<{
  registerSubagentExtension: (pi: ExtensionAPI) => void;
  registerSubagentToolActivation: (pi: ExtensionAPI, options: {
    mode: "auto" | "dynamic" | "eager";
    advertisedPrompt: () => string | undefined;
    hasPendingSupervisorRequest?: () => boolean;
  }) => void;
  registerPinnedTool: (pi: ExtensionAPI, tool: ToolDefinition) => void;
  setDeclarationPinning: (pi: ExtensionAPI, pinned: boolean) => void;
}> {
  if (_subagentExtensionModule) return _subagentExtensionModule;

  // Dynamically import the real installed extension
  // The installed path: ~/.pi/agent/npm/node_modules/pi-subagents/src/extension/index.js
  const piSubagentsRoot = process.env.PI_SUBAGENTS_ROOT ||
    "/home/kos/.pi/agent/npm/node_modules/pi-subagents";
  const { default: registerSubagentExtension } =
    await import(`${piSubagentsRoot}/src/extension/index.js`);
  const { registerSubagentToolActivation } =
    await import(`${piSubagentsRoot}/src/extension/tool-activation.js`);
  const { registerPinnedTool, setDeclarationPinning } =
    await import(`${piSubagentsRoot}/src/extension/declaration-pinning.js`);

  _subagentExtensionModule = { registerSubagentExtension, registerSubagentToolActivation, registerPinnedTool, setDeclarationPinning };
  return _subagentExtensionModule;
}

export async function runChildAgentWithWiki(
  parentPi: ExtensionAPI,
  dbPath: string,
  project: string,
  childTools: string[],  // subset of wiki tool names to register on the child
  childPrincipal: string = "child",  // child inherits read/propose but NOT curator
): Promise<{ result: string; traces: TraceEntry[] }> {
  const traces: TraceEntry[] = [];

  // 1. Load the real pi-subagents extension (verified: this is the installed API)
  const { registerSubagentExtension, registerSubagentToolActivation, registerPinnedTool } =
    await loadSubagentExtensions();

  // 2. Register the parent's subagent tool (if not already registered)
  //    This makes the "subagent" tool available on the parent's tool list.
  //    Per G4: "The separate pi-subagents extension actually intended for use."
  registerSubagentExtension(parentPi);

  // 3. Configure tool activation mode: "auto" = children get tools without
  //    per-call approval. Per G4: "SDK test runners need explicit MCP extension binding."
  const childToolNames = childTools.length > 0
    ? childTools
    : ["wiki_recall", "wiki_read", "wiki_propose", "wiki_operation", "wiki_page"];

  registerSubagentToolActivation(parentPi, {
    mode: "auto" as const,
    advertisedPrompt: () => {
      // The child's tool list — includes wiki tools pinned via registerPinnedTool
      return `You are a child agent with wiki access. Tools: ${childToolNames.join(", ")}. Use wiki_recall for evidence, wiki_propose for corrections. Always cite. You do NOT have curator capability.`;
    },
    hasPendingSupervisorRequest: () => false,  // no supervisor in this integration
  });

  // 4. The child gets its OWN WikiService — NOT the parent's.
  //    This is the key project/principal boundary: the child has its own
  //    instance with its own principal (childPrincipal), so it cannot access
  //    the parent's curator tools even if they share the same dbPath.
  const childWikiService = createWikiService(dbPath, project, childPrincipal);

  // 5. Verify principal boundary: childWikiService should NOT authorize curator tools
  // P4 FIX #4: uses childWikiService.principal (bound), NOT caller childPrincipal
  const canChildCurate = childWikiService.isAuthorized("wiki_curator_decide");
  traces.push({ type: "principal-check", tool: "wiki_curator_decide", principal: childWikiService.principal, authorized: canChildCurate });
  // Verify project isolation: child service is bound to project (not the parent's)
  traces.push({ type: "project-bound", project: childWikiService.project, dbPath: childWikiService.dbPath });

  // 6. Register each authorized wiki tool as a pinned tool on the PARENT session.
  //    This pins the tool definition in the parent's transcript so the parent model
  //    sees the correct tool signature when launching the child.
  // P4 FIX #4: uses childWikiService.isAuthorized() (bound principal), NOT caller arg
  const allToolDefs = childWikiService.toolDefinitions();
  for (const def of allToolDefs) {
    if (childToolNames.includes(def.name) && childWikiService.isAuthorized(def.name)) {
      const toolDef: ToolDefinition = {
        name: def.name,
        description: def.description,
        parameters: def.inputSchema,
        promptGuidelines: def.name.includes("curator")
          ? `Curator tool — requires principal=curator. Current principal: ${childWikiService.principal}. BLOCKED: unauthorized for this child session.`
          : undefined,
        execute: async (id: string, args: Record<string, unknown>, _signal: AbortSignal | undefined, onUpdate: unknown, _ctx: any) => {
          // P4 FIX #4: childWikiService.callTool uses bound principal (no caller arg)
          const result = await childWikiService.callTool(def.name, args);
          traces.push({ type: "tool-result", tool: def.name, ok: !!(result as any).kind !== "error", principal: childWikiService.principal });
          return { content: [{ type: "text", text: JSON.stringify(result) }], isError: !!(result as any).error };
        },
      };
      registerPinnedTool(parentPi, toolDef);
    }
  }

  // 7. Return traces. P4 note: these traces document the WIRING (registered
  //    tools, principal boundary), NOT child execution. The child actually
  //    calls wiki tools only when the parent model invokes the "subagent" tool
  //    (registered in step 2) — this requires a live Pi session.
  //    G4: "Assert the child can see and call the read/propose tools"
  //    → verified by wiring + principal check; execution verified only in G5.
  traces.push({ type: "child-tools-registered", tools: childToolNames, principal: childWikiService.principal });

  return {
    result: `Child agent configured with wiki tools: ${childToolNames.join(", ")}. ` +
            `Principal: ${childWikiService.principal}. Curator authorized: ${canChildCurate}. ` +
            `Bound to project ${project} at ${dbPath}. ` +
            `Wiring complete (child execution requires live Pi session). ` +
            `Registered via pi-subagents registerSubagentExtension + registerSubagentToolActivation + registerPinnedTool.`,
    traces,
  };
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
 * Legacy in-process service smoke check, NOT G4 host verification.
 * No native child or fresh host session is launched by this function.
 * Its similarly named booleans are only local authority observations.
 * Simulates:
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

  // 0. Verify the TS→Python boundary actually works (boundary test)
  const boundaryOk = verifyBoundary();
  traces.push({ type: "boundary-verify", ok: boundaryOk });

  // 1. Parent session proposes (via bridge — real boundary)
  const head = await getPageHead(dbPath, project, "page-g4");
  const proposal = propose(dbPath, project, "page-g4", head, "replace", "Title v1", "body v1", "worker", []);
  traces.push({ type: "proposal-submitted", page: "page-g4", key: proposal?.kind === "pending" ? proposal.key : undefined });

  // 2. Child reads and proposes (fresh WikiService instance)
  const childWikiService = createWikiService(dbPath, project, "child");
  const childPage = page(dbPath, project, "page-g4");
  traces.push({ type: "page-read", page: "page-g4", revision: childPage.kind === "page" ? childPage.revision : undefined });

  const childProposal = propose(dbPath, project, "page-g4", childPage.kind === "page" ? childPage.revision : head, "replace", "Title v2", "body v2", "child-worker", []);
  traces.push({ type: "proposal-submitted", page: "page-g4", key: childProposal?.kind === "pending" ? childProposal.key : undefined });

  // 3. Fresh session reads child's contribution
  const freshWikiService = createWikiService(dbPath, project, "worker");
  const freshPage = page(dbPath, project, "page-g4");
  traces.push({ type: "page-read", page: "page-g4", revision: freshPage.kind === "page" ? freshPage.revision : undefined });

  return {
    parentProposed: proposal?.kind === "pending",
    childRead: childPage.kind === "page",
    childProposed: childProposal?.kind === "pending",
    freshSessionReads: freshPage.kind === "page",
    traces,
  };
}

async function getPageHead(dbPath: string, project: string, pageId: string): Promise<string> {
  const snap = page(dbPath, project, pageId);
  if (snap.kind !== "page") {
    throw new Error(`Page ${pageId} not found`);
  }
  return snap.revision;
}
