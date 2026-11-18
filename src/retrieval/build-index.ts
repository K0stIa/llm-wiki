#!/usr/bin/env node
/** Explicit operator build. Uses only the approved local research embedding. */
import { buildGeneration } from "./qmd-integration.js";
const [database, project, indexRoot, model, ...extra] = process.argv.slice(2);
if (!database || !project || !indexRoot || !model || extra.length) {
  process.stderr.write("Usage: tsx src/retrieval/build-index.ts DATABASE PROJECT INDEX_ROOT CACHED_MODEL\n");
  process.exit(2);
}
try {
  const manifest = await buildGeneration({ database, project, indexRoot, model });
  process.stdout.write(JSON.stringify({ generation: manifest.generation, target: manifest.target,
    modelDigest: manifest.modelDigest, chunks: manifest.documents.length }) + "\n");
} catch (error: unknown) {
  process.stderr.write((error instanceof Error ? error.message : "index build failed") + "\n");
  process.exitCode = 1;
}
