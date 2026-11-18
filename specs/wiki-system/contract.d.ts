// Design contract only. No service or client implementation is shipped here.
// Parse external configuration, MCP input and database rows at their boundaries.
type Brand<T, Name extends string> = T & { readonly __brand: Name };
export type ProjectConnection = Brand<string, "ProjectConnection">;
export type ProjectId = Brand<string, "ProjectId">;
export type AuthorityEpoch = Brand<string, "AuthorityEpoch">;
export type CommitSequence = Brand<number, "CommitSequence">;
export type ProjectRevision = {
  readonly project: ProjectId;
  readonly epoch: AuthorityEpoch;
  readonly sequence: CommitSequence;
};
// Client-chosen logical name; uniqueness is scoped to retained project history.
export type PageId = Brand<string, "PageId">;
// Server-created immutable IDs use creation-epoch/random-UUID, never row counts.
export type SourceId = Brand<string, "SourceId">;
export type PageRevision = Brand<string, "PageRevision">;
export type SourceRevision = Brand<string, "SourceRevision">;
export type IndexGeneration = Brand<string, "IndexGeneration">;
export type ProposalId = Brand<string, "ProposalId">;
export type ProposalCursor = Brand<string, "ProposalCursor">;
// Trusted adapters persist these before sending. They are not model tool inputs.
export type OperationKey = Brand<string, "OperationKey">;
export type Digest = Brand<string, "Digest">;
export type ReviewDigest = Brand<string, "ReviewDigest">;
export type Line = Brand<number, "Line">;
export type NonEmpty<T> = readonly [T, ...T[]];

type Span = { readonly start: Line; readonly end: Line };
// hash covers the entire stored UTF-8 body/text; span is inclusive and 1-based.
export type Citation = Span & { readonly hash: Digest } & (
  | { readonly kind: "page"; readonly page: PageId; readonly revision: PageRevision }
  | { readonly kind: "source"; readonly source: SourceId; readonly revision: SourceRevision }
);
export type PageSnapshot = {
  readonly page: PageId;
  readonly revision: PageRevision;
  readonly hash: Digest;
  readonly title: string;
  readonly markdown: string;
  readonly state: "active" | "retired";
};
export type SourceInput =
  | { readonly kind: "existing"; readonly citation: Citation }
  | { readonly kind: "capture"; readonly title: string; readonly text: string; readonly locator: string };
export type Change =
  | { readonly kind: "create"; readonly page: PageId; readonly title: string; readonly markdown: string }
  | { readonly kind: "replace"; readonly page: PageId; readonly base: PageRevision; readonly title: string; readonly markdown: string }
  | { readonly kind: "retire"; readonly page: PageId; readonly base: PageRevision; readonly reason: string };
export type ProposalInput = {
  readonly key: OperationKey;
  readonly change: Change;
  readonly sources: NonEmpty<SourceInput>;
};
export type ProposalReceipt = {
  readonly kind: "pending";
  readonly key: OperationKey;
  readonly proposal: ProposalId;
  readonly digest: Digest;
};
export type Review =
  | { readonly kind: "create"; readonly change: Extract<Change, { readonly kind: "create" }> }
  | { readonly kind: "replace"; readonly change: Extract<Change, { readonly kind: "replace" }>; readonly base: PageSnapshot; readonly diff: string }
  | { readonly kind: "retire"; readonly change: Extract<Change, { readonly kind: "retire" }>; readonly base: PageSnapshot; readonly diff: string };
export type Decision =
  | { readonly kind: "publish"; readonly reviewedDigest: ReviewDigest }
  | { readonly kind: "reject"; readonly reason: string };
export type DecisionInput = {
  readonly key: OperationKey;
  readonly proposal: ProposalId;
  readonly decision: Decision;
};
export type DecisionOutcome =
  | { readonly kind: "committed"; readonly pageRevision: PageRevision; readonly projectRevision: ProjectRevision }
  | { readonly kind: "rejected"; readonly reason: string }
  | { readonly kind: "conflict"; readonly current: PageRevision | null };
export type ProposalState =
  | { readonly kind: "pending" }
  | { readonly kind: "blocked"; readonly reason: "context-capacity" | "evidence-missing" | "policy" | "review-timeout" }
  | { readonly kind: "decided"; readonly outcome: DecisionOutcome };
export type ProposalSnapshot = {
  readonly id: ProposalId;
  readonly digest: Digest;
  readonly reviewDigest: ReviewDigest;
  readonly review: Review;
  readonly sources: NonEmpty<Citation>;
  readonly state: ProposalState;
};
export type CuratorProposal = ProposalSnapshot & { readonly duplicates: readonly ProposalId[] };
export type OperationState =
  | { readonly kind: "unknown" }
  | { readonly kind: "proposal-accepted"; readonly receipt: ProposalReceipt; readonly snapshot: ProposalSnapshot }
  | { readonly kind: "decision-recorded"; readonly proposal: ProposalId; readonly outcome: DecisionOutcome };
export type PendingProposals = {
  readonly items: readonly {
    readonly proposal: ProposalId;
    readonly digest: Digest;
    readonly state: Exclude<ProposalState, { readonly kind: "decided" }>;
  }[];
  readonly next: ProposalCursor | null;
};
export type IndexState =
  | { readonly kind: "absent" }
  | { readonly kind: "available"; readonly generation: IndexGeneration; readonly indexedThrough: ProjectRevision; readonly modelDigest: Digest };
export type Passage = { readonly text: string } & (
  | { readonly kind: "current-page"; readonly snapshot: ProjectRevision; readonly citation: Extract<Citation, { readonly kind: "page" }> }
  | { readonly kind: "historical-page"; readonly citation: Extract<Citation, { readonly kind: "page" }> }
  | { readonly kind: "source-evidence"; readonly citation: Extract<Citation, { readonly kind: "source" }> }
);
export type ExactRead = Passage | {
  readonly kind: "private-evidence";
  readonly text: string;
  readonly citation: Extract<Citation, { readonly kind: "source" }>;
};
export type RecallResult = {
  readonly snapshot: ProjectRevision;
  readonly index: IndexState;
} & (
  | {
      readonly kind: "context";
      readonly coverage: "hybrid-current" | "hybrid-stale" | "lexical-only";
      readonly evidence:
        | { readonly kind: "candidates"; readonly passages: NonEmpty<Passage> }
        | { readonly kind: "no-matches" };
    }
  | { readonly kind: "not-ready"; readonly reason: "index-lag" | "model-unavailable" }
);
export type RecallInput = {
  readonly query: string;
  readonly atLeast?: ProjectRevision;
  readonly coverage?: "require-hybrid-current" | "best-available";
  /** Compact response JSON bytes, metadata included. Default/hard max 24,000. */
  readonly maxBytes?: number;
};
export interface Knowledge {
  /** Defaults to best-available, with explicit semantic coverage labels. */
  recall(input: RecallInput): Promise<RecallResult>;
  /** Complete immutable body, never a truncated excerpt. Missing revision means current. */
  page(input: { readonly page: PageId; readonly revision?: PageRevision }): Promise<PageSnapshot>;
  /** Exact historical citation; private evidence requires owner or curator scope. */
  read(input: { readonly citation: Citation }): Promise<ExactRead>;
  /** Low-level adapter API. Model-facing MCP schemas omit the key field. */
  propose(input: ProposalInput): Promise<ProposalReceipt>;
  /** Principal-scoped replay/progress, including its own private proposal content. */
  operation(input: { readonly key: OperationKey }): Promise<OperationState>;
}
export interface Curator extends Pick<Knowledge, "recall" | "page" | "read" | "operation"> {
  pendingProposals(input: { readonly cursor?: ProposalCursor; readonly limit?: number }): Promise<PendingProposals>;
  /** Includes full base, proposed body, deletion diff and duplicate-payload flags. */
  proposal(input: { readonly id: ProposalId }): Promise<CuratorProposal>;
  /** Publish only pending work after full review. Reject pending/blocked work without review. */
  decide(input: DecisionInput): Promise<DecisionOutcome>;
}
/** Bound to one authenticated project/principal/epoch. Resolves only after durable prepare. */
export interface HostCallJournal {
  prepare(input: {
    readonly call: string;
    readonly kind: "propose";
    readonly request: Omit<ProposalInput, "key"> & { readonly key?: never };
  }): Promise<{ readonly request: ProposalInput }>;
  prepare(input: {
    readonly call: string;
    readonly kind: "decide";
    readonly request: Omit<DecisionInput, "key"> & { readonly key?: never };
  }): Promise<{ readonly request: DecisionInput }>;
}
export type KnowledgeErrorCode =
  | "unauthorized" | "invalid-input" | "invalid-state" | "key-reuse" | "terminal-decision"
  | "stale-epoch" | "wrong-project" | "not-found" | "busy" | "capacity" | "unavailable";

// Production boundary schemas derive these types or prove equivalence by tests.
export declare function parseConnection(input: unknown): ProjectConnection;
export declare function connectKnowledge(input: ProjectConnection): Promise<Knowledge>;
export declare function connectCurator(input: ProjectConnection): Promise<Curator>;
// Client types are not security. The server authorizes every operation.
