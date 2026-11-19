import { readFileSync } from "node:fs";

type Settings = { device: "vulkan" | "cpu"; depth: number; docTokens: number };

function validSettings(value: unknown): value is Settings {
  if (!value || typeof value !== "object" || Object.keys(value).length !== 3 ||
      !("device" in value && "depth" in value && "docTokens" in value)) return false;
  return (value.device === "vulkan" || value.device === "cpu") &&
    typeof value.depth === "number" && Number.isInteger(value.depth) && value.depth >= 1 && value.depth <= 64 &&
    typeof value.docTokens === "number" && Number.isInteger(value.docTokens) && value.docTokens >= 32 && value.docTokens <= 1024;
}

export function evaluationRerankerSettings(development = false): Settings {
  const profile = JSON.parse(readFileSync(new URL("./g2-reranker-profile.json", import.meta.url), "utf8"));
  if (!profile || Object.keys(profile).length !== 2 || profile.version !== 1 || !validSettings(profile.settings)) {
    throw new Error("invalid G2 reranker profile");
  }
  const approved = profile.settings;
  const { WIKI_EVAL_RERANK_DEVICE: device, WIKI_EVAL_RERANK_DEPTH: depth, WIKI_EVAL_RERANK_TOKENS: docTokens } = process.env;
  if (!development && (
    (device !== undefined && device !== approved.device) ||
    (depth !== undefined && depth !== String(approved.depth)) ||
    (docTokens !== undefined && docTokens !== String(approved.docTokens))
  )) throw new Error("reranker overrides differ from the approved D14 profile");

  const settings = {
    device: device ?? approved.device,
    depth: depth === undefined ? approved.depth : Number(depth),
    docTokens: docTokens === undefined ? approved.docTokens : Number(docTokens),
  };
  if (!validSettings(settings)) throw new Error("invalid G2 reranker settings");
  return settings;
}
