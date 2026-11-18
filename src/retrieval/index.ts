/** P2 public entry point. QMD internals and mutators are not exposed to readers. */
export { recall, buildGeneration, acquireGeneration, cleanupGenerations, fuseRanks, closeQmdReaders } from "./qmd-integration.js";
export type { Binding, Snapshot, Chunk, GenerationPin } from "./qmd-integration.js";
