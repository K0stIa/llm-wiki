#!/usr/bin/env node
/**
 * Eval-only diagnostic: for each question, page order in the lexical list, the vector list and the
 * fused list (before byte/passage limits). Uses the same snapshot, vector search and fusion as recall().
 * CONFIDENTIAL output (page ids) goes to OUT_JSON under .cache/eval/v2; stdout carries counts only.
 *
 *   tsx src/eval/rank_diag_v2.ts DATABASE INDEX_ROOT MODEL QUESTIONS_JSON OUT_JSON
 */
import { readFileSync, writeFileSync } from "node:fs";
import { acquireGeneration, authorityRpc, closeQmdReaders, fuseRanks } from "../retrieval/qmd-integration.js";

const [database, indexRoot, model, questionsPath, out] = process.argv.slice(2);
if (!out) throw new Error("usage: rank_diag_v2.ts DATABASE INDEX_ROOT MODEL QUESTIONS_JSON OUT_JSON");
type Question = { id: string; query: string; project: string };
type Doc = { key: string; kind: string; object: string; hash: string };
const questions: Question[] = JSON.parse(readFileSync(questionsPath, "utf8"));
const pages = (keys: string[], byKey: Map<string, Doc>) => {
  const seen: string[] = [];
  for (const k of keys) { const d = byKey.get(k); if (d && !seen.includes(d.object)) seen.push(d.object); }
  return seen;
};
const result: Record<string, { lexical: string[]; vector: string[]; fused: string[] }> = {};
for (const q of questions) {
  const binding = { database, project: q.project, indexRoot, model };
  const snap = authorityRpc(binding, "wiki_recall_snapshot", { query: q.query }) as { documents: Doc[]; lexical: string[] };
  const byKey = new Map(snap.documents.map(d => [d.key, d]));
  const pin = await acquireGeneration(binding);
  if (!pin) throw new Error("no generation");
  const manifestKeys = new Map(pin.manifest.documents.map((c: { key: string; hash: string }) => [c.key, c]));
  let vector: string[];
  try { vector = (await pin.search(q.query)).map(h => h.key).filter(k => byKey.has(k) && manifestKeys.get(k)?.hash === byKey.get(k)?.hash); }
  finally { await pin.release(); }
  result[q.id] = { lexical: pages(snap.lexical, byKey), vector: pages(vector, byKey), fused: pages(fuseRanks(snap.lexical, vector), byKey) };
}
writeFileSync(out, JSON.stringify(result));
process.stdout.write(`diagnosed ${Object.keys(result).length}\n`);
await closeQmdReaders();
