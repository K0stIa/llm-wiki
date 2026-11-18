import { AsyncLocalStorage } from "node:async_hooks";

export type SearchPlan = Readonly<{
  primary: string;
  supplemental: readonly string[];
  deadlineMs: number;
}>;

type IncompleteReason = "deadline" | "reader-error";

export type SearchResult<Hit> =
  | { kind: "complete"; primary: readonly Hit[]; supplemental: readonly (readonly Hit[])[] }
  | { kind: "supplemental-incomplete"; primary: readonly Hit[]; completed: ReadonlyMap<number, readonly Hit[]>; reason: IncompleteReason }
  | { kind: "primary-unavailable"; reason: IncompleteReason | "overloaded" };

export type SearchDispatch =
  | { kind: "primary"; deadlineMs: number }
  | { kind: "supplemental"; deadlineMs: number; index: number };

type Search<Hit> = (query: string, dispatch: SearchDispatch) => Promise<readonly Hit[]>;

export type ScheduledSearch<Hit> = Readonly<{
  result: Promise<SearchResult<Hit>>;
  drained: Promise<void>;
}>;

type Clock = {
  now(): number;
  after(delayMs: number, operation: () => void): () => void;
};

const monotonicClock: Clock = {
  now: () => performance.now(),
  after(delayMs, operation) {
    const timer = setTimeout(operation, Math.min(Math.ceil(delayMs), 2 ** 31 - 1));
    return () => clearTimeout(timer);
  },
};

type Stage<Hit> =
  | { kind: "primary" }
  | { kind: "supplemental"; primary: readonly Hit[]; completed: Map<number, readonly Hit[]> };

type Job<Hit> = {
  readonly plan: SearchPlan;
  readonly batch: Batch<Hit>;
  readonly search: Search<Hit>;
  readonly resolveResult: (result: SearchResult<Hit>) => void;
  readonly resolveDrained: () => void;
  stage: Stage<Hit>;
  cancelDeadline?: () => void;
  running: boolean;
  finished: boolean;
};

type Batch<Hit> = {
  pending: Set<Job<Hit>>;
  barrier?: () => Promise<void>;
};

function deferred<Value>() {
  let resolve!: (value: Value) => void;
  const promise = new Promise<Value>(fulfill => { resolve = fulfill; });
  return { promise, resolve };
}

/** Serialize native work. A deadline may settle the result before it is safe to release the reader lease. */
export class NativeSearchQueue<Hit> {
  readonly #maxRequests: number;
  readonly #clock: Clock;
  #tail: Batch<Hit> = { pending: new Set() };
  readonly #batches = [this.#tail];
  #admitted = 0;
  #busy = false;

  constructor({ maxRequests, clock = monotonicClock }: { maxRequests: number; clock?: Clock }) {
    if (!Number.isSafeInteger(maxRequests) || maxRequests < 1) {
      throw new RangeError("maxRequests must be a positive safe integer");
    }
    this.#maxRequests = maxRequests;
    this.#clock = clock;
  }

  /** deadlineMs is an absolute performance.now() timestamp. Keep the generation leased until drained. */
  schedule(plan: SearchPlan, search: Search<Hit>): ScheduledSearch<Hit> {
    if (!Number.isFinite(plan.deadlineMs)) throw new RangeError("deadlineMs must be finite");
    if (plan.deadlineMs <= this.#clock.now()) {
      return { result: Promise.resolve({ kind: "primary-unavailable", reason: "deadline" }), drained: Promise.resolve() };
    }
    if (this.#admitted === this.#maxRequests) {
      for (const batch of this.#batches) this.#expireWaiting(batch);
      if (this.#admitted === this.#maxRequests) {
        return { result: Promise.resolve({ kind: "primary-unavailable", reason: "overloaded" }), drained: Promise.resolve() };
      }
    }

    const caller = AsyncLocalStorage.snapshot();
    const result = deferred<SearchResult<Hit>>();
    const drained = deferred<void>();
    const job: Job<Hit> = {
      plan: { ...plan, supplemental: [...plan.supplemental] },
      batch: this.#tail,
      search: (query, dispatch) => caller(search, query, dispatch),
      resolveResult: result.resolve,
      resolveDrained: drained.resolve,
      stage: { kind: "primary" },
      running: false,
      finished: false,
    };
    this.#admitted++;
    job.batch.pending.add(job);
    this.#armDeadline(job);
    queueMicrotask(() => this.#pump());
    return { result: result.promise, drained: drained.promise };
  }

  /** Run maintenance exclusively after physical work admitted so far and before work admitted later. */
  barrier(operation: () => Promise<void>): Promise<void> {
    const caller = AsyncLocalStorage.snapshot();
    return new Promise<void>((resolve, reject) => {
      this.#tail.barrier = async () => {
        try {
          await caller(operation);
          resolve();
        } catch (error) {
          reject(error);
        }
      };
      this.#tail = { pending: new Set() };
      this.#batches.push(this.#tail);
      queueMicrotask(() => this.#pump());
    });
  }

  #armDeadline(job: Job<Hit>) {
    const remaining = job.plan.deadlineMs - this.#clock.now();
    if (remaining <= 0) {
      this.#incomplete(job, "deadline");
      return;
    }
    job.cancelDeadline = this.#clock.after(remaining, () => this.#armDeadline(job));
  }

  #expireWaiting(batch: Batch<Hit>) {
    const now = this.#clock.now();
    for (const job of batch.pending) {
      if (job.plan.deadlineMs <= now) this.#incomplete(job, "deadline");
    }
  }

  #pump() {
    if (this.#busy) return;
    const [batch] = this.#batches;
    this.#expireWaiting(batch);
    const waiting = [...batch.pending];
    const job = waiting.find(candidate => candidate.stage.kind === "primary") ?? waiting[0];
    if (job) {
      batch.pending.delete(job);
      void this.#dispatch(job);
    } else if (batch.barrier) {
      this.#batches.shift();
      this.#busy = true;
      void batch.barrier().then(() => {
        this.#busy = false;
        this.#pump();
      });
    }
  }

  async #dispatch(job: Job<Hit>) {
    this.#busy = true;
    job.running = true;
    const { deadlineMs } = job.plan;
    const stage = job.stage;
    try {
      if (deadlineMs <= this.#clock.now()) {
        this.#incomplete(job, "deadline");
        return;
      }
      const index = stage.kind === "supplemental" ? stage.completed.size : 0;
      const hits = stage.kind === "primary"
        ? await job.search(job.plan.primary, { kind: "primary", deadlineMs })
        : await job.search(job.plan.supplemental[index], { kind: "supplemental", deadlineMs, index });

      if (job.finished) return;
      if (deadlineMs <= this.#clock.now()) {
        this.#incomplete(job, "deadline");
        return;
      }
      if (stage.kind === "primary") {
        if (job.plan.supplemental.length) {
          job.stage = { kind: "supplemental", primary: hits, completed: new Map() };
        } else {
          this.#finish(job, { kind: "complete", primary: hits, supplemental: [] });
        }
        return;
      }
      stage.completed.set(index, hits);
      if (stage.completed.size === job.plan.supplemental.length) {
        this.#finish(job, { kind: "complete", primary: stage.primary, supplemental: [...stage.completed.values()] });
      }
    } catch {
      this.#incomplete(job, deadlineMs <= this.#clock.now() ? "deadline" : "reader-error");
    } finally {
      job.running = false;
      if (job.finished) this.#release(job);
      else job.batch.pending.add(job);
      this.#busy = false;
      queueMicrotask(() => this.#pump());
    }
  }

  #incomplete(job: Job<Hit>, reason: IncompleteReason) {
    const stage = job.stage;
    this.#finish(job, stage.kind === "primary"
      ? { kind: "primary-unavailable", reason }
      : { kind: "supplemental-incomplete", primary: stage.primary, completed: stage.completed, reason });
  }

  #finish(job: Job<Hit>, result: SearchResult<Hit>) {
    if (job.finished) return;
    job.finished = true;
    job.cancelDeadline?.();
    job.resolveResult(result);
    if (!job.running) this.#release(job);
  }

  #release(job: Job<Hit>) {
    job.batch.pending.delete(job);
    this.#admitted--;
    job.resolveDrained();
  }
}
