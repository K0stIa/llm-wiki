/**
 * P2: Derived retrieval — QMD indexing, rank fusion, freshness reporting,
 * bounded context, current-revision checks.
 *
 * Implements RecallResult from contract.d.ts.
 * First release: reuse/adapt QMD indexing, project manifests, rank fusion,
 * freshness reporting, bounded context and current-revision checks.
 */

// Types from contract.d.ts
export type IndexState =
  | { kind: "absent" }
  | { kind: "available"; generation: string; indexedThrough: string; modelDigest: string }
  | { kind: "hybrid-current" }
  | { kind: "hybrid-stale" }
  | { kind: "lexical-only" }
  | { kind: "not-ready"; reason: "index-lag" | "model-unavailable" };

export type RecallInput = {
  query: string;
  atLeast?: string;
  coverage?: "require-hybrid-current" | "best-available";
  maxBytes?: number;
};

export type RecallResult = {
  snapshot: string;
  index: IndexState;
} & (
  | {
      kind: "context";
      coverage: "hybrid-current" | "hybrid-stale" | "lexical-only";
      evidence:
        | { kind: "candidates"; passages: Passage[] }
        | { kind: "no-matches" };
    }
  | { kind: "not-ready"; reason: "index-lag" | "model-unavailable" };
);

export type Passage = {
  text: string;
} & (
  | { kind: "current-page"; snapshot: string; citation: { kind: "page"; page: string; revision: string } }
  | { kind: "historical-page"; citation: { kind: "page"; page: string; revision: string } }
  | { kind: "source-evidence"; citation: { kind: "source"; source: string; revision: string } }
);

export type RecallResult = RecallResult & {
  coverage: "hybrid-current" | "hybrid-stale" | "lexical-only";
};

export interface KnowledgeStore {
  recall(input: RecallInput): RecallResult;
  page(input: { page: string; revision?: string }): PageSnapshot;
  read(input: { citation: Citation }): ExactRead;
  propose(input: ProposalInput): ProposalReceipt;
  operation(input: { key: string }): OperationState;
}

export interface Curator extends KnowledgeStore {
  pendingProposals(input: { cursor?: string; limit?: number }): PendingProposals;
  proposal(input: { id: string }): CuratorProposal;
  decide(input: DecisionInput): DecisionOutcome;
}

// Re-export from authority
export { KnowledgeStore as AuthorityStore } from "../authority/authority";
export { connect_knowledge, connect_curator } from "../authority/authority";

// QMD Store types
export interface QMDStore {
  searchFTS(query: string, limit: number, collectionName?: string): SearchResult[];
  searchVec(query: string, model: string, limit: number): Promise<SearchResult[]>;
  hybridQuery(query: string, options?: HybridQueryOptions): Promise<HybridQueryResult[]>;
  vectorSearchQuery(query: string, options?: VectorSearchOptions): Promise<VectorSearchResult[]>;
  getStatus(): IndexStatus;
  getIndexHealth(): IndexHealthInfo;
}

export interface SearchResult {
  file: string;
  displayPath: string;
  title: string;
  body?: string;
  score: number;
  source: "fts" | "vec";
  docid: string;
  chunkPos?: number;
}

export interface HybridQueryOptions {
  limit?: number;
  minScore?: number;
  candidateLimit?: number;
  explain?: boolean;
  intent?: string;
  skipRerank?: boolean;
}

export interface VectorSearchOptions {
  limit?: number;
  minScore?: number;
  intent?: string;
}

export interface HybridQueryResult {
  file: string;
  displayPath: string;
  title: string;
  body: string;
  bestChunk: string;
  bestChunkPos: number;
  score: number;
  context?: string | null;
  docid: string;
  explain?: HybridQueryExplain;
}

export interface VectorSearchResult {
  file: string;
  displayPath: string;
  title: string;
  body: string;
  score: number;
  context?: string | null;
  docid: string;
}

export interface IndexStatus {
  totalDocuments: number;
  needsEmbedding: number;
  hasVectorIndex: boolean;
}

export interface IndexHealthInfo {
  needsEmbedding: number;
  totalDocs: number;
  daysStale: number | null;
}

export interface HybridQueryExplain {
  ftsScores: number[];
  vectorScores: number[];
  rrf: {
    rank: number;
    positionScore: number;
    weight: number;
    baseScore: number;
    totalScore: number;
  };
  rerankScore: number;
  blendedScore: number;
}
