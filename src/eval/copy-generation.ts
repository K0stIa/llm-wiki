import { join } from "node:path";
import { copyGenerationSnapshot } from "../retrieval/qmd-integration.js";

const [source, destination, expectedModelDigest, ...projects] = process.argv.slice(2);
if (!source || !destination || !expectedModelDigest || projects.length === 0) {
  throw new Error("expected source directory, destination directory, expected model digest, and projects");
}
for (const project of projects) {
  await copyGenerationSnapshot(
    { database: join(source, "authority.db"), indexRoot: join(source, "indexes"), project },
    { indexRoot: join(destination, "indexes"), project },
    expectedModelDigest,
  );
}
