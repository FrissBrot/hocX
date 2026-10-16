import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearDraft,
  flushOutbox,
  getOfflineSnapshot,
  initializeOfflineStore,
  queueMutation,
  readDraft,
  saveDraft,
} from "./offline-store";

describe("offline-store", () => {
  beforeEach(() => {
    localStorage.clear();
    Object.defineProperty(navigator, "onLine", { configurable: true, value: false });
    vi.stubGlobal("crypto", { randomUUID: () => "mutation-id" });
    initializeOfflineStore();
  });

  it("coalesces repeated edits of the same field to the newest payload", () => {
    queueMutation({ key: "protocol-text:7", path: "/text/7", method: "PUT", body: '{"content":"a"}' });
    queueMutation({ key: "protocol-text:7", path: "/text/7", method: "PUT", body: '{"content":"ab"}' });

    const stored = JSON.parse(localStorage.getItem("hocx-offline-outbox-v1") ?? "[]");
    expect(stored).toHaveLength(1);
    expect(stored[0]).toMatchObject({ id: "mutation-id", key: "protocol-text:7", body: '{"content":"ab"}' });
    expect(getOfflineSnapshot().pending).toBe(1);
  });

  it("persists and clears crash-recovery drafts", () => {
    saveDraft("protocol-notes:4", "Lokaler Entwurf");
    expect(readDraft("protocol-notes:4")).toBe("Lokaler Entwurf");
    clearDraft("protocol-notes:4");
    expect(readDraft("protocol-notes:4")).toBeNull();
  });

  it("loescht nach erfolgreichem Senden keine waehrenddessen eingereihte neuere Fassung (Audit MAIN-FE-011)", async () => {
    let counter = 0;
    vi.stubGlobal("crypto", { randomUUID: () => `id-${++counter}` });
    queueMutation({ key: "protocol-text:7", path: "/text/7", method: "PUT", body: '{"content":"a"}' });
    Object.defineProperty(navigator, "onLine", { configurable: true, value: true });
    let respond!: (response: Response) => void;
    const fetchMock = vi.fn(() => new Promise<Response>((resolve) => { respond = resolve; }));
    vi.stubGlobal("fetch", fetchMock);

    const flushing = flushOutbox();
    // Waehrend der erste Body unterwegs ist, tippt die Person weiter.
    queueMutation({ key: "protocol-text:7", path: "/text/7", method: "PUT", body: '{"content":"ab"}' });
    respond(new Response(null, { status: 200 }));
    await flushing;

    const stored = JSON.parse(localStorage.getItem("hocx-offline-outbox-v1") ?? "[]");
    expect(stored).toHaveLength(1);
    expect(stored[0]).toMatchObject({ body: '{"content":"ab"}', id: "id-2" });
    // Nachgelagerte Flush-Timer sollen nach dem Test nicht mehr senden.
    Object.defineProperty(navigator, "onLine", { configurable: true, value: false });
    vi.unstubAllGlobals();
  });

  it("sendet blockierte Eintraege nicht bei jedem Flush erneut", async () => {
    queueMutation({ key: "protocol-text:8", path: "/text/8", method: "PUT", body: '{"content":"x"}' });
    const stored = JSON.parse(localStorage.getItem("hocx-offline-outbox-v1") ?? "[]");
    stored[0].blocked = true;
    localStorage.setItem("hocx-offline-outbox-v1", JSON.stringify(stored));
    Object.defineProperty(navigator, "onLine", { configurable: true, value: true });
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await flushOutbox();

    expect(fetchMock).not.toHaveBeenCalled();
    Object.defineProperty(navigator, "onLine", { configurable: true, value: false });
    vi.unstubAllGlobals();
  });
});
