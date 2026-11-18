/**
 * Named crash points in the derived-index builder. Same contract as
 * src/authority/faults.py, which holds the single registry (POINTS) that both
 * languages' placements are tested against. process.exit does not run pending
 * finally blocks, so a crash leaves exactly the on-disk state of that moment.
 */
export const FAULT_EXIT = 97;
const POINTS = new Set(["generation.after-stage", "generation.after-rename", "generation.after-pointer"]);

export function faultPoint(name: string): void {
  if (!POINTS.has(name)) throw new Error(`unregistered fault point ${name}`);
  // Other names belong to the Python side (and are validated there).
  if (process.env.WIKI_TEST_FAULT_POINT === name) process.exit(FAULT_EXIT);
}
