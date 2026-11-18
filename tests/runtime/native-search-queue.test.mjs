import assert from "node:assert/strict";
import { AsyncLocalStorage } from "node:async_hooks";
import { test } from "node:test";
import { NativeSearchQueue } from "../../src/retrieval/native-search-queue.js";

const flush = () => new Promise(resolve => setImmediate(resolve));

function fixture(maxRequests = 10) {
  let now = 0;
  const timers = new Set();
  const clock = {
    now: () => now,
    after(delay, run) {
      const timer = { at: now + delay, run };
      timers.add(timer);
      return () => timers.delete(timer);
    },
  };
  function advance(to, { runTimers = true } = {}) {
    now = to;
    if (!runTimers) return;
    const elapsed = [...timers].filter(timer => timer.at <= now);
    for (const timer of elapsed) {
      if (timers.delete(timer)) timer.run();
    }
  }

  const context = new AsyncLocalStorage();
  const queue = new NativeSearchQueue({ maxRequests, clock });
  const started = [];
  let active;
  function schedule(primary, supplemental = [], deadlineMs = 100) {
    return context.run(primary, () =>
      queue.schedule({ primary, supplemental, deadlineMs }, async (query, dispatch) => {
        assert.equal(active, undefined, "overlapping native operations");
        assert.equal(context.getStore(), primary);
        const pending = Promise.withResolvers();
        started.push([query, dispatch.kind, dispatch.index]);
        active = pending;
        try {
          return await pending.promise;
        } finally {
          assert.equal(context.getStore(), primary);
          active = undefined;
        }
      }));
  }
  const succeed = async value => {
    active.resolve([value]);
    await flush();
  };
  const fail = async () => {
    active.reject(new Error("native reader failed"));
    await flush();
  };
  return { queue, started, schedule, advance, succeed, fail, context };
}

test("FIFO primaries take precedence between single supplemental dispatches", async () => {
  const f = fixture();
  const first = f.schedule("a", ["a0", "a1"]);
  await flush();
  await f.succeed("A");
  const second = f.schedule("b", ["b0"]);
  const third = f.schedule("c");
  await f.succeed("A0");
  await f.succeed("B");
  await f.succeed("C");
  await f.succeed("A1");
  await f.succeed("B0");
  assert.deepEqual(f.started, [
    ["a", "primary", undefined],
    ["a0", "supplemental", 0],
    ["b", "primary", undefined],
    ["c", "primary", undefined],
    ["a1", "supplemental", 1],
    ["b0", "supplemental", 0],
  ]);
  assert.deepEqual(await first.result, {
    kind: "complete", primary: ["A"], supplemental: [["A0"], ["A1"]],
  });
  assert.deepEqual(await second.result, {
    kind: "complete", primary: ["B"], supplemental: [["B0"]],
  });
  assert.deepEqual(await third.result, { kind: "complete", primary: ["C"], supplemental: [] });
  await Promise.all([first.drained, second.drained, third.drained]);
});

test("ten admissions include the active request and expiry frees a waiting admission", async () => {
  const f = fixture();
  const active = f.schedule("active");
  const expiring = f.schedule("expired", [], 2);
  const waiting = Array.from({ length: 8 }, (_, index) => f.schedule(String(index)));
  assert.deepEqual(await f.schedule("over-cap").result, {
    kind: "primary-unavailable", reason: "overloaded",
  });
  await flush();
  f.advance(2, { runTimers: false });
  const next = f.schedule("next");
  await expiring.drained;
  assert.deepEqual(await expiring.result, { kind: "primary-unavailable", reason: "deadline" });
  for (const query of ["active", "0", "1", "2", "3", "4", "5", "6", "7", "next"]) {
    await f.succeed(query);
  }
  assert.deepEqual(f.started.map(([query]) => query), [
    "active", "0", "1", "2", "3", "4", "5", "6", "7", "next",
  ]);
  await Promise.all([active.drained, ...waiting.map(job => job.drained), next.drained]);
});

test("queued jobs expire and drain even while another native search remains active", async () => {
  const f = fixture();
  const blocker = f.schedule("blocker");
  const queued = f.schedule("queued", ["never"], 2);
  await flush();
  f.advance(2);
  assert.deepEqual(await queued.result, { kind: "primary-unavailable", reason: "deadline" });
  await queued.drained;
  assert.deepEqual(f.started.map(([query]) => query), ["blocker"]);
  await f.succeed("unblocked");
  await blocker.drained;
  assert.deepEqual(f.started.map(([query]) => query), ["blocker"]);
});

test("active timeout returns indexed partials and retains admission until native failure settles", async () => {
  const f = fixture(1);
  const first = f.schedule("a", ["a0", "a1", "a2"], 5);
  await flush();
  await f.succeed("A");
  await f.succeed("A0");
  f.advance(5);
  const partial = {
    kind: "supplemental-incomplete", primary: ["A"],
    completed: new Map([[0, ["A0"]]]), reason: "deadline",
  };
  assert.deepEqual(await first.result, partial);
  let drained = false;
  void first.drained.then(() => { drained = true; });
  await flush();
  assert.equal(drained, false);
  assert.deepEqual(await f.schedule("over-cap").result, {
    kind: "primary-unavailable", reason: "overloaded",
  });
  await f.fail();
  await first.drained;
  assert.deepEqual(await first.result, partial);
  const second = f.schedule("b");
  await flush();
  await f.succeed("B");
  assert.deepEqual(await second.result, { kind: "complete", primary: ["B"], supplemental: [] });
  assert.deepEqual(f.started.map(([query]) => query), ["a", "a0", "a1", "b"]);
});

test("a waiting supplemental expiry preserves earlier work and drains immediately", async () => {
  const f = fixture();
  const first = f.schedule("a", ["a0", "a1"], 5);
  await flush();
  await f.succeed("A");
  const second = f.schedule("b");
  await f.succeed("A0");
  f.advance(5);
  await first.drained;
  assert.deepEqual(await first.result, {
    kind: "supplemental-incomplete", primary: ["A"],
    completed: new Map([[0, ["A0"]]]), reason: "deadline",
  });
  await f.succeed("B");
  await second.drained;
  assert.deepEqual(f.started.map(([query]) => query), ["a", "a0", "b"]);
});

test("absolute deadline wins over a native result before delayed timers run", async () => {
  const f = fixture();
  const alreadyExpired = f.schedule("expired", [], 0);
  await alreadyExpired.drained;
  assert.deepEqual(await alreadyExpired.result, { kind: "primary-unavailable", reason: "deadline" });
  const late = f.schedule("late", ["never"], 4);
  await flush();
  f.advance(4, { runTimers: false });
  await f.succeed("LATE");
  assert.deepEqual(await late.result, { kind: "primary-unavailable", reason: "deadline" });
  await late.drained;
  assert.deepEqual(f.started.map(([query]) => query), ["late"]);
});

test("reader errors distinguish unavailable primary from completed supplemental work", async () => {
  const f = fixture();
  const primaryError = f.schedule("missing", ["never"]);
  await flush();
  await f.fail();
  assert.deepEqual(await primaryError.result, { kind: "primary-unavailable", reason: "reader-error" });
  const supplementalError = f.schedule("a", ["a0", "a1", "a2"]);
  await flush();
  await f.succeed("A");
  await f.succeed("A0");
  await f.fail();
  assert.deepEqual(await supplementalError.result, {
    kind: "supplemental-incomplete", primary: ["A"],
    completed: new Map([[0, ["A0"]]]), reason: "reader-error",
  });
  await Promise.all([primaryError.drained, supplementalError.drained]);
  assert.deepEqual(f.started.map(([query]) => query), ["missing", "a", "a0", "a1"]);
});

test("a barrier waits for physical drain, runs exclusively, and fences later admission", async () => {
  const f = fixture();
  const old = f.schedule("old", ["old0"], 2);
  await flush();
  const dispose = Promise.withResolvers();
  let closed = false;
  const barrier = f.context.run("close", () => f.queue.barrier(async () => {
    assert.equal(f.context.getStore(), "close");
    closed = true;
    await dispose.promise;
    throw new Error("dispose failed");
  }));
  const newer = f.schedule("newer");
  f.advance(2);
  assert.deepEqual(await old.result, { kind: "primary-unavailable", reason: "deadline" });
  assert.equal(closed, false);
  await f.succeed("OLD");
  await old.drained;
  assert.equal(closed, true);
  assert.deepEqual(f.started.map(([query]) => query), ["old"]);
  const observed = assert.rejects(barrier, /dispose failed/);
  dispose.resolve();
  await observed;
  await flush();
  await f.succeed("NEW");
  assert.deepEqual(await newer.result, { kind: "complete", primary: ["NEW"], supplemental: [] });
});
