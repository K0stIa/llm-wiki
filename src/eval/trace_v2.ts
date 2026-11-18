#!/usr/bin/env node
/** Development recall observer. The Python runner supplies verified development inputs and private output paths. */
import { readFileSync, writeFileSync } from "node:fs";
import { resolve, join } from "node:path";
import { fileURLToPath } from "node:url";
import * as z from "zod/v4";
import { buildGeneration, recall, closeQmdReaders, observeRecall, recallSpansOverlap } from "../retrieval/qmd-integration.js";
import type { RecallTrace, Reranker } from "../retrieval/qmd-integration.js";

const goldSchema = z.object({ page: z.string().min(1), span: z.string().min(1).nullable(), revision: z.literal("current").optional() });
const developmentSchema = z.strictObject({
  subset: z.literal("development"),
  questions: z.array(z.object({
    id: z.string(), query: z.string(), project: z.string(), expected: z.string(), gold: z.array(goldSchema),
  })).nonempty(),
});
type Gold = z.infer<typeof goldSchema>;
type Document = RecallTrace["documents"][number];

const matchesGold = (document: Document, project: string, gold: Gold, exact: boolean) =>
  document.span.kind === "page" && document.span.object === gold.page && document.passage.snapshot?.project === project &&
  (!exact || gold.span !== null && document.passage.text.includes(gold.span));

export function candidateKeys(lists: RecallTrace) {
  return new Set([...lists.lexical, ...lists.exact, ...lists.vector, ...lists.clauseVectors.flat(), ...lists.expansionCandidates]);
}

type Oracle = { status: "proved" | "unknown"; matched: number; required: number; bytes: number; witness: Document[] };

export function feasibleEvidence(
  documents: Document[], project: string, facts: Gold[],
  packing: Pick<RecallTrace, "baseBytes" | "cap" | "passageLimit">,
  visitLimit = 100_000,
): Oracle {
  const { baseBytes, cap, passageLimit } = packing;
  const masks = (document: Document) => facts.reduce((mask, fact, index) =>
    matchesGold(document, project, fact, fact.span !== null) ? mask | 1n << BigInt(index) : mask, 0n);
  const entries = documents.map(document => ({ document, mask: masks(document) }))
    .filter(({ document, mask }) => mask && baseBytes + document.bytes <= cap)
    .sort((a, b) => a.document.bytes - b.document.bytes || a.document.key.localeCompare(b.document.key));
  const suffix = new Array<bigint>(entries.length + 1).fill(0n);
  for (let i = entries.length - 1; i >= 0; i--) suffix[i] = suffix[i + 1] | entries[i].mask;
  const count = (bits: bigint) => {
    let n = 0;
    for (; bits; bits &= bits - 1n) n++;
    return n;
  };
  const possible = count(suffix[0]);
  let visits = 0, exhausted = false;
  let best: Oracle = { status: "proved", matched: 0, required: facts.length, bytes: baseBytes, witness: [] };
  const selected: Document[] = [];
  const search = (start: number, covered: bigint, bytes: number): void => {
    if (best.matched === possible || count(covered | suffix[start]) <= best.matched) return;
    if (visits++ >= visitLimit) { exhausted = true; return; }
    for (let i = start; i < entries.length && best.matched < possible && !exhausted; i++) {
      const { document, mask } = entries[i];
      const next = covered | mask;
      const size = bytes + document.bytes + Number(selected.length > 0);
      if (size > cap) break;
      if (next === covered || selected.some(other => recallSpansOverlap(other.span, document.span))) continue;
      selected.push(document);
      const matched = count(next);
      if (matched > best.matched) best = { ...best, matched, bytes: size, witness: [...selected] };
      if (selected.length < passageLimit) search(i + 1, next, size);
      selected.pop();
    }
  };
  if (passageLimit > 0) search(0, 0n, baseBytes);
  return exhausted ? { ...best, status: "unknown" } : best;
}

function witnessRecord({ witness, ...oracle }: Oracle) {
  return { ...oracle, keys: witness.map(document => document.key) };
}

export function evidenceStages(keys: Set<string>, lists: RecallTrace, union: Set<string>) {
  const hits = (order: string[]) => order.filter(key => keys.has(key));
  const stages = {
    lexical: hits(lists.lexical), exact: hits(lists.exact), vector: hits(lists.vector),
    clauses: lists.clauseVectors.map(hits), clauseWinners: hits(lists.clauseWinners),
    candidates: hits([...union]), fused: hits(lists.fused), rerankHead: hits(lists.head),
    rerankOrder: hits(lists.rerankOrder), ranked: hits(lists.ranked), direct: hits(lists.direct),
    expansionCandidates: hits(lists.expansionCandidates), expanded: hits(lists.expanded), ordered: hits(lists.ordered),
    emitted: hits(lists.emitted), skippedForOverlap: hits(lists.skippedForOverlap),
    skippedForBytes: hits(lists.skippedForBytes), skippedForPassageLimit: hits(lists.skippedForPassageLimit),
  };
  const loss = stages.emitted.length ? "emitted"
    : !stages.candidates.length ? "not-retrieved"
    : stages.skippedForBytes.length && stages.skippedForPassageLimit.length ? "byte-and-passage-limits"
    : stages.skippedForBytes.length ? "byte-cap"
    : stages.skippedForPassageLimit.length ? "passage-limit"
    : stages.skippedForOverlap.length ? "overlap"
    : "not-selected";
  return { ...stages, loss };
}

function frozenReranker(): Reranker {
  const model = process.env.WIKI_EVAL_RERANKER;
  if (!model) throw new Error("set WIKI_EVAL_RERANKER to the approved cached GGUF");
  const device = z.literal("vulkan").parse(process.env.WIKI_EVAL_RERANK_DEVICE ?? "vulkan");
  const depth = z.literal("24").parse(process.env.WIKI_EVAL_RERANK_DEPTH ?? "24");
  const docTokens = z.literal("512").parse(process.env.WIKI_EVAL_RERANK_TOKENS ?? "512");
  return { model, device, depth: Number(depth), docTokens: Number(docTokens) };
}

async function main() {
  const [database, indexRoot, model, questionsPath, outDir, reuse] = process.argv.slice(2);
  if (!outDir) throw new Error("usage: trace_v2.ts DATABASE INDEX_ROOT MODEL DEV_QUESTIONS_JSON OUT_DIRECTORY");
  const { questions } = developmentSchema.parse(JSON.parse(readFileSync(questionsPath, "utf8")));
  const { model: rerankerModel, ...profile } = frozenReranker();
  const reranker = { model: rerankerModel, ...profile };
  const traces: Record<string, unknown> = {};
  const rankings: Record<string, unknown> = {};
  const oracleRankings: Record<string, unknown> = {};
  let stages: Record<string, number> = {};
  const observed: { lists?: RecallTrace } = {};
  const readObserved = (): RecallTrace | undefined => observed.lists;
  try {
    const buildStart = performance.now();
    if (reuse !== "--reuse-generation") {
      for (const project of new Set(questions.map(q => q.project))) await buildGeneration({ database, project, indexRoot, model });
    }
    const buildSeconds = (performance.now() - buildStart) / 1000;
    observeRecall({ stage: (name, ms) => { stages[name] = (stages[name] ?? 0) + ms; }, lists: data => { observed.lists = data; } });
    for (const [i, question] of questions.entries()) {
      stages = {};
      delete observed.lists;
      const result = await recall({ database, project: question.project, indexRoot, model, reranker },
        { query: question.query, coverage: "require-hybrid-current" });
      const lists = readObserved();
      const coverage = "coverage" in result ? result.coverage : "not-current";
      const degradation = ("degradation" in result ? result.degradation : lists?.degradation) ?? null;
      const ranking = {
        status: result.kind === "context" ? "ok" : result.kind, coverage, degradation,
        seconds: stages.total / 1000, bytes: Buffer.byteLength(JSON.stringify(result)),
        passages: "evidence" in result ? result.evidence.passages : [],
      };
      rankings[question.id] = ranking;
      oracleRankings[question.id] = question.expected === "answer"
        ? { ...ranking, status: "evidence-unknown", passages: [] }
        : ranking;
      traces[question.id] = { stages, result: result.kind, degradation, coverage };
      if (lists) {
        const union = candidateKeys(lists);
        const { documents, ...orders } = lists;
        const evidence = question.gold.map(fact => {
          const keys = (exact: boolean) => new Set(documents.filter(doc => matchesGold(doc, question.project, fact, exact)).map(doc => doc.key));
          return {
            page: evidenceStages(keys(false), lists, union),
            span: fact.span === null ? { loss: "span-unscorable" } : evidenceStages(keys(true), lists, union),
          };
        });
        const candidateComplete = evidence.every(fact => fact.page.candidates.length > 0);
        const candidates = documents.filter(document => union.has(document.key));
        const candidateOracle = feasibleEvidence(candidates, question.project, question.gold, lists);
        const hasFullCandidateWitness = candidateOracle.matched === candidateOracle.required;
        const authorityOracle = hasFullCandidateWitness ? candidateOracle : feasibleEvidence(documents, question.project, question.gold, lists);
        if (question.expected === "answer") {
          const fullWitness = authorityOracle.status === "proved" && authorityOracle.matched === authorityOracle.required;
          oracleRankings[question.id] = { ...ranking,
            status: fullWitness ? "ok" : authorityOracle.status === "unknown" ? "evidence-unknown" : "evidence-incomplete",
            bytes: authorityOracle.bytes, passages: authorityOracle.witness.map(document => document.passage),
          };
        }
        traces[question.id] = {
          stages, result: result.kind, degradation, coverage, candidateComplete, evidence,
          candidateOracle: witnessRecord(candidateOracle), authorityOracle: witnessRecord(authorityOracle),
          lists: { ...orders, documents: documents.filter(document => union.has(document.key) ||
            question.gold.some(gold => matchesGold(document, question.project, gold, false)))
            .map(({ key, span, bytes, passage }) => ({ key, ...span, bytes, hash: passage.hash, snapshot: passage.snapshot })) },
        };
      }
      if ((i + 1) % 25 === 0) process.stdout.write(`traced ${i + 1}/${questions.length}\n`);
    }
    const save = (name: string, data: unknown) => writeFileSync(join(outDir, name), JSON.stringify(data), { mode: 0o600, flag: "wx" });
    save("trace.json", { version: 2, subset: "development", reranker: profile, traces });
    save("raw.json", { buildSeconds, rankings, reranker: profile });
    save("oracle-raw.json", { buildSeconds, rankings: oracleRankings, reranker: profile });
    process.stdout.write(`traced ${questions.length}\n`);
  } finally {
    observeRecall(undefined);
    await closeQmdReaders();
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
