import { join } from "node:path";
import { copyGenerationSnapshot } from "../retrieval/qmd-integration.js";

const [source, destination, ...projects] = process.argv.slice(2);
if (!source || !destination || projects.length === 0) {
  throw new Error("expected source directory, destination directory, and projects");
}
for (const project of projects) {
  await copyGenerationSnapshot(
    { database: join(source, "authority.db"), indexRoot: join(source, "indexes"), project },
    { indexRoot: join(destination, "indexes"), project },
  );
}
