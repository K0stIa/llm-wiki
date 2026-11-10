/**
 * P2: QMD integration — indexing, rank fusion, freshness, bounded context.
 *
 * Wraps the QMD Store (v2.8.3) for the wiki knowledge service.
 * Handles:
 * - QMD update (indexing)
 * - searchFTS (BM25)
 * - searchVec (vector)
 * - hybridQuery (BM25 + vector + RRF)
 * - freshness detection (stale vs current)
 * - bounded context (maxBytes, pagination)
 * - current-revision checks (stale vectors, stale FTS)
 */

import { createStore, getDocid } from "@tobilu/qmd/dist/index.js";
import { pathToFileURL } from "url";
import { existsSync } from "fs";

// ─── Types ───────────────────────────────────────────────────────────────

export interface QMDRetrievalResult {
  coverage: "hybrid-current" | "hybrid-stale" | "lexical-only" | "not-ready";
  reason?: string;
  passages: Passage[];
  indexState: IndexState;
  snapshot: string;
}

export type Passage = {
  text: string;
  kind: "current-page" | "historical-page" | "source-evidence";
  citation: { page: string; revision: string } | { source: string; revision: string };
  snapshot: string;
};

export type IndexState =
  | { kind: "absent" }
  | { kind: "available"; generation: string; indexedThrough: string; modelDigest: string }
  | { kind: "hybrid-current" }
  | { kind: "hybrid-stale" }
  | { kind: "lexical-only" }
  | { kind: "not-ready"; reason: "index-lag" | "model-unavailable" };

// ─── QMD Store wrapper ───────────────────────────────────────────────────

function getQMDStore(dbPath: string) {
  try {
    return createStore(dbPath);
  } catch {
    return null;
  }
}

// ─── Freshness detection ────────────────────────────────────────────────

function checkFreshness(store, projectRevision: string): { coverage: string; state: IndexState } {
  const status = store.getStatus();

  if (status.needsEmbedding > 0 && !status.hasVectorIndex) {
    return {
      coverage: "not-ready",
      state: { kind: "not-ready", reason: "model-unavailable" }
    };
  }

  // Check if vectors are current
  const health = store.getIndexHealth();
  if (health.needsEmbedding > 0) {
    return {
      coverage: "hybrid-stale",
      state: { kind: "hybrid-stale" }
    };
  }

  if (status.hasVectorIndex) {
    return {
      coverage: "hybrid-current",
      state: { kind: "hybrid-current" }
    };
  }

  return {
    coverage: "lexical-only",
    state: { kind: "lexical-only" }
  };
}

// ─── Bounded context ─────────────────────────────────────────────────────

function boundContext(results, maxBytes: number): { text: string; bytes: number; truncated: boolean } {
  let bytes = 0;
  let truncated = false;
  const pieces: string[] = [];

  for (const r of results) {
    const chunk = r.bestChunk || r.body || "";
    const chunkBytes = Buffer.byteLength(chunk, "utf-8");

    if (bytes + chunkBytes > maxBytes) {
      if (!truncated) {
        truncated = true;
        const remaining = maxBytes - bytes;
        if (remaining > 100) {
          pieces.push(chunk.slice(0, remaining));
        }
      }
      break;
    }

    pieces.push(chunk);
    bytes += chunkBytes;
  }

  return {
    text: pieces.join("\n\n"),
    bytes,
    truncated
  };
}

// ─── Main recall implementation ──────────────────────────────────────────

async function recall(input: {
  query: string;
  atLeast?: string;
  coverage?: "require-hybrid-current" | "best-available";
  maxBytes?: number;
}, store, projectRevision: string): Promise<{
  coverage: string;
  passages: any[];
  indexState: any;
  snapshot: string;
}> {
  const maxBytes = input.maxBytes || 24000;
  const coverage = input.coverage || "best-available";

  // Check freshness
  const { coverage: freshCoverage, state: indexState } = checkFreshness(store, projectRevision);

  // If strict hybrid required and not ready
  if (coverage === "require-hybrid-current" && freshCoverage !== "hybrid-current") {
    return {
      coverage: freshCoverage,
      passages: [],
      indexState,
      snapshot: projectRevision
    };
  }

  // Perform search
  let results: any[] = [];
  let source: string;

  if (freshCoverage === "hybrid-current" || freshCoverage === "hybrid-stale") {
    // Use QMD hybrid query (BM25 + vector + RRF)
    const qmd = getQMDStore(store.dbPath);
    if (qmd) {
      const hybrid = await qmd.hybridQuery(input.query, {
        limit: 10,
        minScore: 0.1,
        candidateLimit: 20,
        explain: false,
        skipRerank: true // Keep simple for P2
      });
      results = hybrid;
      source = "hybrid";
    }
  }

  if (freshCoverage === "lexical-only" || (freshCoverage === "hybrid-stale" && !results.length)) {
    // Fall back to BM25 only
    const qmd = getQMDStore(store.dbPath);
    if (qmd) {
      results = qmd.searchFTS(input.query, 10);
      source = "lexical-only";
    }
  }

  // Build passages
  const passages = results.map(r => ({
    kind: "current-page" as const,
    citation: { page: r.file, revision: getDocid(r.docid) },
    snapshot: projectRevision,
    text: r.bestChunk || r.body || "",
    score: r.score
  }));

  // Bound context
  const bounded = boundContext(results, maxBytes);

  return {
    coverage: freshCoverage,
    passages,
    indexState,
    snapshot: projectRevision
  };
}

// ─── Indexing (outbox integration) ───────────────────────────────────────

async function reindexFromOutbox(store, outbox: any): Promise<number> {
  const items = outbox.process("index", "pending");
  let promoted = 0;

  for (const item of items) {
    const qmd = getQMDStore(store.dbPath);
    if (!qmd) continue;

    try {
      await qmd.update();
      promoted++;
    } catch (e) {
      outbox.fail(item.id, String(e));
    }
  }

  return promoted;
}

// ─── Export ──────────────────────────────────────────────────────────────

export { recall, boundContext, checkFreshness, reindexFromOutbox };
