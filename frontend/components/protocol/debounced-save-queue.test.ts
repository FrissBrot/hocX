import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createDebouncedSaveQueue } from "./debounced-save-queue";

describe("createDebouncedSaveQueue", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("sendet entprellt nur den letzten Wert", async () => {
    const send = vi.fn(async () => true);
    const queue = createDebouncedSaveQueue<string>(700, send);
    queue.schedule("a", "H");
    queue.schedule("a", "Ha");
    queue.schedule("a", "Hallo");
    await vi.advanceTimersByTimeAsync(700);
    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith("a", "Hallo");
  });

  it("flushAll speichert sofort und wartet, bevor es zurückkehrt (Abschliessen-Regression)", async () => {
    const order: string[] = [];
    let release: (() => void) | undefined;
    const send = vi.fn(
      (key: string, value: string) =>
        new Promise<boolean>((resolve) => {
          order.push(`start:${key}:${value}`);
          release = () => {
            order.push(`done:${key}`);
            resolve(true);
          };
        })
    );
    const queue = createDebouncedSaveQueue<string>(700, send);
    queue.schedule("a", "letzter Satz");
    expect(queue.hasPending()).toBe(true);

    let flushed: boolean | undefined;
    const flushing = queue.flushAll().then((ok) => {
      flushed = ok;
      order.push("flushed");
    });
    // Ohne Wartezeit gestartet, aber noch nicht fertig.
    await Promise.resolve();
    await Promise.resolve();
    expect(send).toHaveBeenCalledWith("a", "letzter Satz");
    expect(flushed).toBeUndefined();

    release?.();
    await flushing;
    expect(flushed).toBe(true);
    expect(order).toEqual(["start:a:letzter Satz", "done:a", "flushed"]);
    // Der alte Timer darf nicht noch einmal senden.
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(1);
    expect(queue.hasPending()).toBe(false);
  });

  it("flushAll meldet false, wenn eine Speicherung scheitert", async () => {
    const send = vi.fn(async (_key: string, value: string) => value !== "kaputt");
    const queue = createDebouncedSaveQueue<string>(700, send);
    queue.schedule("a", "gut");
    queue.schedule("b", "kaputt");
    expect(await queue.flushAll()).toBe(false);
  });

  it("flushAll meldet false bei einer Ausnahme im Sender", async () => {
    const queue = createDebouncedSaveQueue<string>(700, async () => {
      throw new Error("offline");
    });
    queue.schedule("a", "x");
    expect(await queue.flushAll()).toBe(false);
  });

  it("serialisiert Speicherungen desselben Schlüssels", async () => {
    const calls: string[] = [];
    let releaseFirst: (() => void) | undefined;
    const send = vi.fn((_key: string, value: string) => {
      calls.push(value);
      if (value === "1") return new Promise<boolean>((resolve) => (releaseFirst = () => resolve(true)));
      return Promise.resolve(true);
    });
    const queue = createDebouncedSaveQueue<string>(100, send);
    queue.schedule("a", "1");
    await vi.advanceTimersByTimeAsync(100);
    queue.schedule("a", "2");
    const flushing = queue.flushAll();
    await Promise.resolve();
    expect(calls).toEqual(["1"]);
    releaseFirst?.();
    expect(await flushing).toBe(true);
    expect(calls).toEqual(["1", "2"]);
  });
});
