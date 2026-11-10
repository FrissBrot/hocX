import { afterEach, describe, expect, it, vi } from "vitest";

import { analyzeFiles } from "./pool";

const posted: unknown[] = [];

class FailingWorker {
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  constructor() {
    // Worker-Skript nicht ladbar: genau ein error-Event, danach nie wieder eine Reaktion.
    setTimeout(() => this.onerror?.(new Event("error")), 0);
  }
  postMessage(message: unknown) {
    posted.push(message);
  }
  terminate() {}
}

class SilentWorker {
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  postMessage(message: unknown) {
    posted.push(message);
  }
  terminate() {}
}

function files(count: number): File[] {
  return Array.from({ length: count }, (_, index) => new File([new Uint8Array([index])], `bild-${index}.jpg`, { type: "image/jpeg" }));
}

afterEach(() => {
  vi.unstubAllGlobals();
  posted.length = 0;
});

describe("analyzeFiles mit defektem Worker (IMGMETA-005)", () => {
  it("analysiert nach einem Worker-Ladefehler alle Dateien im Hauptthread statt zu hängen", async () => {
    vi.stubGlobal("Worker", FailingWorker);
    const results = await analyzeFiles(files(5), { concurrency: 2 });
    expect(results).toHaveLength(5);
    expect(results.every(Boolean)).toBe(true);
    // Nach dem Fehler wird nichts mehr an den toten Worker geschickt.
    expect(posted.length).toBeLessThanOrEqual(2);
  });

  it("weicht bei einem stummen Worker nach dem Timeout auf den Hauptthread aus", async () => {
    vi.stubGlobal("Worker", SilentWorker);
    const results = await analyzeFiles(files(4), { concurrency: 2, workerTimeoutMs: 20 });
    expect(results).toHaveLength(4);
    expect(results.every(Boolean)).toBe(true);
    expect(posted.length).toBe(2); // je Slot nur ein Versuch, danach Hauptthread
  });
});
