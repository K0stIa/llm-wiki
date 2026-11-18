import { execFile, type ChildProcess } from "node:child_process";

type Job = {
  argv: string[]; input: string; expires: number; timer?: ReturnType<typeof setTimeout>;
  child?: ChildProcess; failure?: Error;
  resolve: (value: unknown) => void; reject: (error: unknown) => void;
};
/** Bounded subprocess reads. Deadline includes admission wait; active failure waits
 * for child close before releasing its slot or resolving the caller's lifetime. */
export class BoundedJsonRpc {
  private readonly queue: Job[] = [];
  private active = 0;
  private queuedBytes = 0;
  constructor(private readonly options = { maxActive: 4, maxPending: 32, deadlineMs: 30000, maxBuffer: 64 * 1024 * 1024 }) {
    for (const value of Object.values(options)) if (!Number.isSafeInteger(value) || value < 1) throw new Error("invalid RPC limits");
  }
  get activeCount() { return this.active; }
  get pendingCount() { return this.queue.length; }
  run(argv: string[], args: unknown): Promise<unknown> {
    const expires = performance.now() + this.options.deadlineMs;
    return new Promise((resolve, reject) => {
      if (this.active >= this.options.maxActive && this.queue.length >= this.options.maxPending) {
        reject(new Error("authority RPC capacity exceeded")); return;
      }
      let input: string;
      try {
        input = JSON.stringify(args);
        if (typeof input !== "string" || Buffer.byteLength(input) > this.options.maxBuffer) throw new Error("authority RPC input exceeds limit");
      } catch (error) { reject(error); return; }
      const bytes = Buffer.byteLength(input);
      if (this.active >= this.options.maxActive && this.queuedBytes + bytes > this.options.maxBuffer) {
        reject(new Error("authority RPC queued input capacity exceeded")); return;
      }
      const job: Job = { argv: [...argv], input, expires, resolve, reject };
      const remaining = expires - performance.now();
      if (remaining <= 0) { reject(new Error("authority RPC deadline exceeded")); return; }
      job.timer = setTimeout(() => {
        job.failure = new Error("authority RPC deadline exceeded");
        if (job.child) job.child.kill("SIGKILL");
        else {
          const index = this.queue.indexOf(job);
          if (index >= 0) { this.queue.splice(index, 1); this.queuedBytes -= Buffer.byteLength(job.input); }
          job.reject(job.failure);
        }
      }, remaining);
      this.queue.push(job);
      this.queuedBytes += bytes;
      this.pump();
    });
  }
  private pump() {
    while (this.active < this.options.maxActive && this.queue.length) {
      const job = this.queue.shift()!;
      this.queuedBytes -= Buffer.byteLength(job.input);
      if (performance.now() >= job.expires) {
        clearTimeout(job.timer); job.reject(new Error("authority RPC deadline exceeded")); continue;
      }
      this.active++;
      let completed = false;
      const complete = (error: Error | null, stdout: string) => {
        if (completed) return;
        completed = true;
        clearTimeout(job.timer);
        this.active--;
        try {
          if (job.failure) throw job.failure;
          if (error) throw error;
          if (performance.now() >= job.expires) throw new Error("authority RPC deadline exceeded");
          const parsed: unknown = JSON.parse(stdout);
          if (performance.now() >= job.expires) throw new Error("authority RPC deadline exceeded");
          job.resolve(parsed);
        } catch (failure) { job.reject(failure); }
        this.pump();
      };
      try {
        job.child = execFile(job.argv[0], job.argv.slice(1), {
          encoding: "utf8", maxBuffer: this.options.maxBuffer, killSignal: "SIGKILL",
        }, complete);
        job.child.stdin!.on("error", (error: Error) => {
          job.failure ??= error; job.child?.kill("SIGKILL");
        });
        job.child.stdin!.end(job.input);
      } catch (error) { complete(error as Error, ""); }
    }
  }
}
const authorityReads = new BoundedJsonRpc();
export const readAuthorityJson = (argv: string[], args: unknown) => authorityReads.run(argv, args);
