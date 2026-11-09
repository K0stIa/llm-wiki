// Compile-only contract tests. These do not execute a production service.
import type {
  AuthorityEpoch, CommitSequence, Curator, Digest, ExactRead, HostCallJournal, Knowledge,
  OperationKey, PageId, PageRevision, Passage, ProjectId, ProjectRevision,
  ProposalId, ProposalInput, ProposalSnapshot, RecallInput, Review, ReviewDigest,
} from "../contract.js";

declare const project: ProjectId;
declare const epoch: AuthorityEpoch;
declare const sequence: CommitSequence;
declare const page: PageId;
declare const pageRevision: PageRevision;
declare const proposal: ProposalId;
declare const key: OperationKey;
declare const digest: Digest;
declare const reviewDigest: ReviewDigest;
declare const reader: Knowledge;
declare const curator: Curator;
declare const journal: HostCallJournal;
declare const proposalInput: ProposalInput;

const barrier: ProjectRevision = { project, epoch, sequence };
const bestAvailable: RecallInput = { query: "rotated tokens", coverage: "best-available", maxBytes: 24_000 };
const strict: RecallInput = { query: "rotated tokens", atLeast: barrier, coverage: "require-hybrid-current" };

async function fullPageAndReviewContract(): Promise<void> {
  const full = await reader.page({ page, revision: pageRevision });
  const body: string = full.markdown;
  const hash: Digest = full.hash;
  const revision: PageRevision = full.revision;
  await reader.propose({
    key, change: { kind: "replace", page, base: revision, title: full.title, markdown: body },
    sources: [{ kind: "capture", title: "test", text: body, locator: "fixture" }],
  });
  const pending = await curator.pendingProposals({ limit: 20 });
  const ids: readonly ProposalId[] = pending.items.map(item => item.proposal);
  const snapshot = await curator.proposal({ id: proposal });
  const reviewed: ReviewDigest = snapshot.reviewDigest;
  const duplicates: readonly ProposalId[] = snapshot.duplicates;
  if (snapshot.review.kind === "replace") {
    const baseBody: string = snapshot.review.base.markdown;
    const diff: string = snapshot.review.diff;
    void [baseBody, diff];
  }
  await curator.decide({ key, proposal, decision: { kind: "publish", reviewedDigest: reviewed } });
  void [hash, ids, duplicates];
}

async function privateOperationContract(): Promise<void> {
  const state = await reader.operation({ key });
  if (state.kind === "proposal-accepted") {
    const own: ProposalSnapshot = state.snapshot;
    const content: Review = own.review;
    void content;
  }
}

async function rejectionAndJournalContract(): Promise<void> {
  // Pending or blocked work can be rejected without pretending it was reviewed.
  await curator.decide({ key, proposal, decision: { kind: "reject", reason: "context-capacity" } });
  const intent = await journal.prepare({
    call: "trusted-host/session/call-1", kind: "propose",
    request: { change: proposalInput.change, sources: proposalInput.sources },
  });
  const journaledKey: OperationKey = intent.request.key;
  await reader.propose(intent.request);
  const rejection = await journal.prepare({
    call: "trusted-curator/session/call-2", kind: "decide",
    request: { proposal, decision: { kind: "reject", reason: "review-timeout" } },
  });
  await curator.decide(rejection.request);
  void journaledKey;
}

// @ts-expect-error publication still requires a complete review attestation.
void curator.decide({ key, proposal, decision: { kind: "publish" } });
// @ts-expect-error a payload digest cannot substitute for the review attestation.
void curator.decide({ key, proposal, decision: { kind: "publish", reviewedDigest: digest } });
// @ts-expect-error the curator client cannot submit its own proposals.
void curator.propose(proposalInput);
// @ts-expect-error the journal, not the model-facing request, assigns the key.
void journal.prepare({ call: "x", kind: "propose", request: { change: proposalInput.change, sources: proposalInput.sources, key } });
// @ts-expect-error pre-keyed variables also cannot bypass the journal's key ownership.
void journal.prepare({ call: "x", kind: "propose", request: proposalInput });

// @ts-expect-error a barrier must include project and epoch, not only a counter.
const legacyBarrier: ProjectRevision = sequence;
// @ts-expect-error a restore-safe revision is not numerically comparable.
const numericBarrier: number = barrier;
// @ts-expect-error a proposal digest cannot attest a complete review bundle.
const wrongReviewDigest: ReviewDigest = digest;
// @ts-expect-error retired tail-scan coverage is not part of the simplified API.
const removedMode: RecallInput = { query: "x", coverage: "allow-degraded" };

type ReplacementReview = Extract<Review, { readonly kind: "replace" }>;
declare const replacement: ReplacementReview["change"];
// @ts-expect-error replacement review requires the complete base and deletion diff.
const partialReview: ReplacementReview = { kind: "replace", change: replacement };
declare const ownProposal: ProposalSnapshot;
// @ts-expect-error a key-free proposal snapshot cannot disclose another actor's key.
const otherActorsKey: OperationKey = ownProposal.key;
declare const privateRead: Extract<ExactRead, { readonly kind: "private-evidence" }>;
// @ts-expect-error private evidence must not enter public recall passages.
const leakedEvidence: Passage = privateRead;

void [bestAvailable, strict, reviewDigest, fullPageAndReviewContract, privateOperationContract, rejectionAndJournalContract];
