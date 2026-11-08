import { describe, expect, it } from "vitest";
import { runSerializedByKey } from "./serialize-by-key";

describe("runSerializedByKey", () => {
  it("führt Änderungen desselben Schlüssels nacheinander aus, andere parallel", async () => {
    const log: string[] = [];
    let releaseFirst!: () => void;
    const first = runSerializedByKey("a", () => new Promise<void>((resolve) => { log.push("a1 start"); releaseFirst = () => { log.push("a1 end"); resolve(); }; }));
    const second = runSerializedByKey("a", async () => { log.push("a2"); });
    const other = runSerializedByKey("b", async () => { log.push("b"); });
    await other;
    expect(log).toEqual(["a1 start", "b"]);
    releaseFirst();
    await Promise.all([first, second]);
    expect(log).toEqual(["a1 start", "b", "a1 end", "a2"]);
  });

  it("läuft nach einem Fehler weiter", async () => {
    const failed = runSerializedByKey("c", async () => { throw new Error("x"); });
    const next = runSerializedByKey("c", async () => "ok");
    await expect(failed).rejects.toThrow("x");
    await expect(next).resolves.toBe("ok");
  });
});
