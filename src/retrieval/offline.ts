/** Research-only cached weights. No model resolution through remote URIs. */
import { openSync, readSync, closeSync, realpathSync, mkdirSync } from "node:fs";
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import http from "node:http";
import https from "node:https";
import net from "node:net";
import { syncBuiltinESMExports } from "node:module";

export const APPROVED_MODEL_SHA256 = "b5ce9d77a3fc4b3b39ccb5643c36777911cc4eb46a66962eadfa3f5f60490d63";
/** Experimental cross-encoder reranker (Qwen3-Reranker-0.6B Q8_0); opt-in, eval v2 development only. */
export const RERANK_MODEL_SHA256 = "22c9979ce4fbcdc5acdc310c6641c32797eff1aa980b8f7a2db8a8ea23429a48";
export const digest = (data: string | Buffer) => createHash("sha256").update(data).digest("hex");
/** Full hash on every validation, without retaining a model-sized Buffer. */
export function fileDigest(path: string): string {
  const fd = openSync(path, "r");
  try {
    const hash = createHash("sha256");
    const buffer = Buffer.allocUnsafe(64 * 1024);
    let length: number;
    while ((length = readSync(fd, buffer, 0, buffer.length, null)) !== 0) {
      hash.update(buffer.subarray(0, length));
    }
    return hash.digest("hex");
  } finally { closeSync(fd); }
}
// Four bounded native hashing lanes. Each request hashes all bytes anew; no
// metadata/content cache. Coreutils hashes off the JS event loop; its caller still awaits completion.
const hashLanes: Promise<void>[] = Array.from({ length: 4 }, () => Promise.resolve());
let nextHashLane = 0;
export function fileDigestAsync(path: string): Promise<string> {
  const lane = nextHashLane++ % hashLanes.length;
  const result = hashLanes[lane].then(() => new Promise<string>((resolve, reject) => {
    execFile("/usr/bin/sha256sum", ["--zero", "--", path],
      { encoding: "utf8", timeout: 30000, maxBuffer: 64 * 1024 }, (error, stdout) => {
        if (error) { reject(error); return; }
        const match = /^([a-f0-9]{64})  /.exec(stdout);
        if (!match || !stdout.endsWith("\0")) { reject(new Error("invalid model digest response")); return; }
        resolve(match[1]);
      });
  }));
  hashLanes[lane] = result.then(() => {}, () => {});
  return result;
}
export function checkedModel(path: string): string {
  const local = realpathSync(path);
  if (fileDigest(local) !== APPROVED_MODEL_SHA256) throw new Error("unapproved cached embedding hash");
  return local;
}
export async function offlineQmd(model: string, cache: string) {
  const local = realpathSync(model);
  // Validate inside the serialized native operation immediately before setup.
  // This is a fresh full-file digest, never a reusable receipt or stat cache.
  if (await fileDigestAsync(local) !== APPROVED_MODEL_SHA256) throw new Error("unapproved cached embedding hash");
  const denied = () => { throw new Error("QMD network access forbidden"); };
  http.request = http.get = https.request = https.get = denied;
  net.connect = net.createConnection = net.Socket.prototype.connect = denied;
  globalThis.fetch = denied;
  syncBuiltinESMExports();
  process.env.QMD_FORCE_CPU = "1"; // packaged CPU runtime: build never, skipDownload true
  process.env.QMD_EMBED_MODEL = local;
  process.env.XDG_CACHE_HOME = cache;
  mkdirSync(cache, { recursive: true });
  return import("@tobilu/qmd");
}
