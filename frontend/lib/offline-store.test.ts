import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  bindOfflineStoreToUser,
  clearDraft,
  clearOfflineStore,
  flushOutbox,
  flushPendingOfflineWrites,
  getOfflineSnapshot,
  initializeOfflineStore,
  queueMutation,
  readDraft,
  saveDraft,
} from "./offline-store";

describe("offline-store", () => {
  beforeEach(() => {
    clearOfflineStore();
    localStorage.clear();
    Object.defineProperty(navigator, "onLine", { configurable: true, value: false });
    vi.stubGlobal("crypto", { randomUUID: () => "mutation-id" });
    initializeOfflineStore();
  });

  it("coalesces repeated edits of the same field to the newest payload", () => {
    queueMutation({ key: "protocol-text:7", path: "/text/7", method: "PUT", body: '{"content":"a"}' });
    queueMutation({ key: "protocol-text:7", path: "/text/7", method: "PUT", body: '{"content":"ab"}' });
    flushPendingOfflineWrites();

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
    flushPendingOfflineWrites();

    const stored = JSON.parse(localStorage.getItem("hocx-offline-outbox-v1") ?? "[]");
    expect(stored).toHaveLength(1);
    expect(stored[0]).toMatchObject({ body: '{"content":"ab"}', id: "id-2" });
    // Nachgelagerte Flush-Timer sollen nach dem Test nicht mehr senden.
    Object.defineProperty(navigator, "onLine", { configurable: true, value: false });
    vi.unstubAllGlobals();
  });

  it("sendet blockierte Eintraege nicht bei jedem Flush erneut", async () => {
    queueMutation({ key: "protocol-text:8", path: "/text/8", method: "PUT", body: '{"content":"x"}' });
    flushPendingOfflineWrites();
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

  it("discards another account's outbox and drafts before this account can send them", () => {
    bindOfflineStoreToUser("user-a");
    queueMutation({ key: "protocol-text:7", path: "/text/7", method: "PUT", body: '{"content":"geheim"}' });
    saveDraft("protocol-text:7", "geheim");

    bindOfflineStoreToUser("user-b");

    expect(localStorage.getItem("hocx-offline-outbox-v1")).toBeNull();
    expect(readDraft("protocol-text:7")).toBeNull();
    expect(getOfflineSnapshot().pending).toBe(0);
  });

  it("keeps the own outbox when the same account comes back", () => {
    bindOfflineStoreToUser("user-a");
    queueMutation({ key: "protocol-text:7", path: "/text/7", method: "PUT", body: '{"content":"a"}' });

    bindOfflineStoreToUser("user-a");

    expect(getOfflineSnapshot().pending).toBe(1);
  });

  it("removes everything on logout", () => {
    bindOfflineStoreToUser("user-a");
    queueMutation({ key: "protocol-text:7", path: "/text/7", method: "PUT", body: '{"content":"a"}' });
    saveDraft("session-notes:3", "Notiz");

    clearOfflineStore();

    expect(Object.keys(localStorage).filter((key) => key.startsWith("hocx-"))).toEqual([]);
    expect(getOfflineSnapshot().pending).toBe(0);
  });

  describe("Schreibpuffer (pro Tastendruck kein localStorage)", () => {
    afterEach(() => {
      vi.restoreAllMocks();
      vi.useRealTimers();
    });

    it("liest und schreibt beim Weitertippen im selben Feld kein localStorage", () => {
      queueMutation({ key: "protocol-text:7", path: "/text/7", method: "PUT", body: '{"content":"a"}' });
      saveDraft("protocol-text:7", "a");
      const getItem = vi.spyOn(Storage.prototype, "getItem");
      const setItem = vi.spyOn(Storage.prototype, "setItem");

      for (const content of ["ab", "abc", "abcd"]) {
        expect(readDraft("protocol-text:7")).not.toBeNull();
        saveDraft("protocol-text:7", content);
        queueMutation({ key: "protocol-text:7", path: "/text/7", method: "PUT", body: JSON.stringify({ content }) });
      }

      expect(getItem).not.toHaveBeenCalled();
      expect(setItem).not.toHaveBeenCalled();
      // Lesen sieht trotzdem den neuesten Stand
      expect(readDraft("protocol-text:7")).toBe("abcd");
      expect(getOfflineSnapshot().pending).toBe(1);
    });

    it("speichert spätestens nach 300 ms gebündelt", () => {
      vi.useFakeTimers();
      queueMutation({ key: "protocol-text:7", path: "/text/7", method: "PUT", body: '{"content":"a"}' });
      saveDraft("protocol-text:7", "a");
      vi.advanceTimersByTime(150);
      // Weitertippen verschiebt den Zeitpunkt nicht (kein endloses Hinauszögern)
      saveDraft("protocol-text:7", "ab");
      queueMutation({ key: "protocol-text:7", path: "/text/7", method: "PUT", body: '{"content":"ab"}' });
      expect(localStorage.getItem("hocx-draft-v1:protocol-text:7")).toBeNull();

      vi.advanceTimersByTime(150);

      expect(localStorage.getItem("hocx-draft-v1:protocol-text:7")).toBe("ab");
      const stored = JSON.parse(localStorage.getItem("hocx-offline-outbox-v1") ?? "[]");
      expect(stored).toHaveLength(1);
      expect(stored[0]).toMatchObject({ body: '{"content":"ab"}' });
    });

    it.each([
      ["pagehide", () => window.dispatchEvent(new Event("pagehide"))],
      ["beforeunload", () => window.dispatchEvent(new Event("beforeunload"))],
      ["visibilitychange (hidden)", () => {
        Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
        document.dispatchEvent(new Event("visibilitychange"));
        Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
      }],
    ])("schreibt beim Verlassen des Tabs sofort (%s) - kein Datenverlust beim Schliessen", (_name, leave) => {
      vi.useFakeTimers();
      saveDraft("protocol-text:9", "Zuletzt getippt");
      queueMutation({ key: "protocol-text:9", path: "/text/9", method: "PUT", body: '{"content":"Zuletzt getippt"}' });

      leave();

      expect(localStorage.getItem("hocx-draft-v1:protocol-text:9")).toBe("Zuletzt getippt");
      expect(JSON.parse(localStorage.getItem("hocx-offline-outbox-v1") ?? "[]")).toHaveLength(1);
    });

    it("behält beim Speichern Einträge, die ein anderer Tab inzwischen eingereiht hat", () => {
      queueMutation({ key: "protocol-text:1", path: "/text/1", method: "PUT", body: '{"content":"hier"}' });
      // Anderer Tab schreibt direkt in localStorage
      localStorage.setItem("hocx-offline-outbox-v1", JSON.stringify([
        { id: "fremd", key: "session-notes:2", path: "/notes/2", method: "PUT", body: "{}", createdAt: 1, attempts: 0 },
      ]));

      flushPendingOfflineWrites();

      const stored = JSON.parse(localStorage.getItem("hocx-offline-outbox-v1") ?? "[]");
      expect(stored.map((item: { key: string }) => item.key).sort()).toEqual(["protocol-text:1", "session-notes:2"]);
    });

    it("verwirft einen gelöschten Entwurf auch, wenn er noch nicht gespeichert war", () => {
      vi.useFakeTimers();
      saveDraft("protocol-text:5", "x");
      clearDraft("protocol-text:5");
      vi.advanceTimersByTime(400);
      expect(readDraft("protocol-text:5")).toBeNull();
      expect(localStorage.getItem("hocx-draft-v1:protocol-text:5")).toBeNull();
    });
  });
});
