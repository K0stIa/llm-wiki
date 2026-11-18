#!/usr/bin/env node
/**
 * Run real hybrid recall for eval v2 questions and save raw rankings.
 * CONFIDENTIAL: input and output contain corpus text; both live under .cache/eval/v2.
 * stdout carries counts only.
 *
 *   tsx src/eval/rank_v2.ts DATABASE INDEX_ROOT MODEL QUESTIONS_JSON OUT_JSON
 * WIKI_EVAL_RERANKER=<pinned reranker GGUF> enables the experimental rerank stage;
 * WIKI_EVAL_RERANK_DEVICE (vulkan|cpu), WIKI_EVAL_RERANK_DEPTH, WIKI_EVAL_RERANK_TOKENS tune it.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { performance } from "node:perf_hooks";
import { buildGeneration, recall, closeQmdReaders, RERANK_DEPTH, RERANK_DOC_TOKENS } from "../retrieval/qmd-integration.js";

const [database, indexRoot, model, questionsPath, out] = process.argv.slice(2);
if (!out) throw new Error("usage: rank_v2.ts DATABASE INDEX_ROOT MODEL QUESTIONS_JSON OUT_JSON");
type Question = { id: string; query: string; project: string };
const env = process.env;
function positiveInt(name: string): number | undefined {
  const raw = env[name];
  if (raw === undefined || raw === "") return undefined;
  if (!/^[1-9][0-9]*$/.test(raw)) throw new Error(`${name} must be a positive integer`);
  return Number(raw);
}
const device = env.WIKI_EVAL_RERANK_DEVICE ?? "vulkan";
if (device !== "vulkan" && device !== "cpu") throw new Error("WIKI_EVAL_RERANK_DEVICE must be vulkan or cpu");
const reranker = env.WIKI_EVAL_RERANKER ? { model: env.WIKI_EVAL_RERANKER, device: device as "vulkan" | "cpu",
  depth: positiveInt("WIKI_EVAL_RERANK_DEPTH"), docTokens: positiveInt("WIKI_EVAL_RERANK_TOKENS") } : undefined;
const questions: Question[] = JSON.parse(readFileSync(questionsPath, "utf8"));
const projects = [...new Set(questions.map(q => q.project))];
const buildStart = performance.now();
for (const project of projects) await buildGeneration({ database, project, indexRoot, model });
const buildSeconds = (performance.now() - buildStart) / 1000;
const rankings: Record<string, unknown> = {};
let n = 0;
for (const q of questions) {
  const start = performance.now();
  const result = await recall({ database, project: q.project, indexRoot, model, reranker }, { query: q.query, coverage: "require-hybrid-current" });
  const seconds = (performance.now() - start) / 1000;
  const bytes = Buffer.byteLength(JSON.stringify(result));
  if (!("coverage" in result) || result.coverage !== "hybrid-current" || !("evidence" in result)) {
    rankings[q.id] = { status: "not-current", seconds, bytes, passages: [] };
  } else {
    if ("degradation" in result) throw new Error(`recall degraded: ${String(result.degradation)}`);
    rankings[q.id] = { status: "ok", coverage: result.coverage, seconds, bytes, passages: result.evidence.passages };
  }
  if (++n % 25 === 0) process.stdout.write(`ranked ${n}/${questions.length}\n`);
}
writeFileSync(out, JSON.stringify({ buildSeconds, rankings,
  reranker: reranker ? { device: reranker.device, depth: reranker.depth ?? RERANK_DEPTH, docTokens: reranker.docTokens ?? RERANK_DOC_TOKENS } : null }));
process.stdout.write(`ranked ${n}/${questions.length}; build ${buildSeconds.toFixed(1)}s\n`);
await closeQmdReaders();
