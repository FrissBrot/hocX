import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { blockIdOfLockKey, createDeferredUnlock, createSerialQueue } from "./block-save-queue";

/** Nachgebauter Server mit optimistischer Sperre wie PATCH /protocol-element-blocks/{id}. */
function fakeServer() {
  let version = 1;
  let config: unknown = null;
  const pending: Array<() => void> = [];
  return {
    get version() {
      return version;
    },
    get config() {
      return config;
    },
    patch(next: unknown, expected: number) {
      // Antwort erst, wenn der Test sie freigibt (langsames Netz)
      return new Promise<{ version: number }>((resolve, reject) => {
        pending.push(() => {
          if (expected !== version) {
            reject(Object.assign(new Error("config_conflict"), { status: 409 }));
            return;
          }
          version += 1;
          config = next;
          resolve({ version });
        });
      });
    },
    /** Wartet, bis eine Anfrage ansteht, und beantwortet sie. */
    async releaseNext() {
      for (let tick = 0; tick < 50 && pending.length === 0; tick += 1) await Promise.resolve();
      expect(pending.length).toBeGreaterThan(0);
      pending.shift()!();
    },
    async releaseAll() {
      while (pending.length > 0) {
        pending.shift()!();
        await Promise.resolve();
        await Promise.resolve();
        await Promise.resolve();
      }
    },
  };
}

describe("createSerialQueue (Collaboration-Audit F-04)", () => {
  it("zwei schnelle Speicherungen desselben Blocks: keine 409, beide Änderungen auf dem Server", async () => {
    const server = fakeServer();
    const queue = createSerialQueue();
    let knownVersion = 1;
    const conflicts: string[] = [];
    const save = (next: string[]) =>
      queue.run("block-1", async () => {
        try {
          const result = await server.patch(next, knownVersion);
          knownVersion = result.version;
        } catch {
          conflicts.push(next.join(","));
        }
      });

    // Aufzählungspunkt bearbeitet (Blur-Save), dann sofort «+»
    const first = save(["Budget 2027"]);
    const second = save(["Budget 2027", ""]);
    // Der zweite PATCH startet erst nach der Antwort des ersten
    expect(queue.pending("block-1")).toBe(2);
    await server.releaseNext();
    await first;
    await server.releaseNext();
    await second;

    expect(conflicts).toEqual([]);
    expect(server.config).toEqual(["Budget 2027", ""]);
    expect(server.version).toBe(3);
    expect(queue.pending("block-1")).toBe(0);
  });

  it("ohne Serialisierung (Stand 1.6.0) schlägt der zweite PATCH mit 409 fehl", async () => {
    const server = fakeServer();
    const knownVersion = 1; // aus dem letzten Render, für beide gleich
    const settled = Promise.allSettled([server.patch(["Budget 2027"], knownVersion), server.patch(["Budget 2027", ""], knownVersion)]);
    await server.releaseAll();
    const results = await settled;
    expect(results.map((r) => r.status)).toEqual(["fulfilled", "rejected"]);
    expect(server.config).toEqual(["Budget 2027"]);
  });

  it("verschiedene Blöcke laufen unabhängig", async () => {
    const queue = createSerialQueue();
    const order: string[] = [];
    let releaseA: () => void = () => {};
    const a = queue.run("a", () => new Promise<void>((resolve) => {
      order.push("a:start");
      releaseA = () => {
        order.push("a:done");
        resolve();
      };
    }));
    const b = queue.run("b", async () => {
      order.push("b");
    });
    await b;
    expect(order).toEqual(["a:start", "b"]);
    releaseA();
    await a;
  });

  it("ein Fehler hält die Kette nicht an und whenIdle wartet auch auf später Angehängtes", async () => {
    const queue = createSerialQueue();
    const failing = queue.run("x", async () => {
      throw new Error("Netz");
    });
    await expect(failing).rejects.toThrow("Netz");
    let done = false;
    let release: () => void = () => {};
    void queue.run("x", () => new Promise<void>((resolve) => {
      release = resolve;
    }));
    const idle = queue.whenIdle("x").then(() => {
      done = true;
    });
    await Promise.resolve();
    void queue.run("x", async () => {});
    expect(done).toBe(false);
    release();
    await idle;
    expect(done).toBe(true);
    expect(queue.pending("x")).toBe(0);
  });
});

describe("createDeferredUnlock (Collaboration-Audit F-01)", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("gibt die Sperre erst nach der Speicherung samt field_update frei", async () => {
    const events: string[] = [];
    let finishSave: () => void = () => {};
    const locks = createDeferredUnlock(
      { lockField: (key) => events.push(`lock:${key}`), unlockField: (key) => events.push(`unlock:${key}`) },
      () => new Promise<void>((resolve) => {
        events.push("flush");
        finishSave = () => {
          events.push("put+field_update");
          resolve();
        };
      })
    );
    locks.lockField("block-1");
    locks.unlockField("block-1"); // Escape direkt nach dem Tippen
    expect(events).toEqual(["lock:block-1"]);
    await vi.advanceTimersByTimeAsync(0);
    expect(events).toEqual(["lock:block-1", "flush"]);
    finishSave();
    await vi.advanceTimersByTimeAsync(0);
    expect(events).toEqual(["lock:block-1", "flush", "put+field_update", "unlock:block-1"]);
  });

  it("behält die Sperre, wenn der Block vor der Freigabe wieder betreten wird", async () => {
    const unlock = vi.fn();
    let finishSave: () => void = () => {};
    const locks = createDeferredUnlock(
      { lockField: vi.fn(), unlockField: unlock },
      () => new Promise<void>((resolve) => {
        finishSave = resolve;
      })
    );
    locks.lockField("block-1");
    locks.unlockField("block-1");
    await vi.advanceTimersByTimeAsync(0);
    locks.lockField("block-1");
    finishSave();
    await vi.advanceTimersByTimeAsync(0);
    expect(unlock).not.toHaveBeenCalled();
  });

  it("gibt auch frei, wenn die Speicherung scheitert", async () => {
    const unlock = vi.fn();
    const locks = createDeferredUnlock({ lockField: vi.fn(), unlockField: unlock }, () => Promise.reject(new Error("offline")));
    locks.lockField("block-1-cell-2-3");
    locks.unlockField("block-1-cell-2-3");
    await vi.advanceTimersByTimeAsync(0);
    expect(unlock).toHaveBeenCalledWith("block-1-cell-2-3");
  });

  it("findet die Block-ID auch in Zellschlüsseln", () => {
    expect(blockIdOfLockKey("block-6f1c2b9e-0000-4000-8000-000000000001")).toBe("6f1c2b9e-0000-4000-8000-000000000001");
    expect(blockIdOfLockKey("block-6f1c2b9e-0000-4000-8000-000000000001-cell-r1-c2")).toBe("6f1c2b9e-0000-4000-8000-000000000001");
    expect(blockIdOfLockKey("element-titles")).toBeNull();
  });
});
