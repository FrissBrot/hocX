import { beforeEach, describe, expect, it, vi } from "vitest";

import { clearOfflineStore, readDraft, saveDraft } from "@/lib/offline-store";
import { createTextDraftStore, decideDraftRestore, settleDraftAfterSave } from "./text-drafts";

describe("decideDraftRestore", () => {
  it("übernimmt nichts ohne Entwurf", () => {
    expect(decideDraftRestore(null, null, "Server")).toBe("none");
  });

  it("erkennt einen schon gespeicherten Entwurf (Neuladen vor der Antwort)", () => {
    expect(decideDraftRestore("Server", "alt", "Server")).toBe("saved");
    expect(decideDraftRestore("Server", null, "Server")).toBe("saved");
  });

  it("stellt einen Entwurf wieder her, wenn der Server unverändert ist", () => {
    expect(decideDraftRestore("Mein Text", "Server", "Server")).toBe("restore");
  });

  it("meldet einen Konflikt, wenn jemand anderes den Text inzwischen geändert hat", () => {
    expect(decideDraftRestore("Mein Text", "Server alt", "Fassung von B")).toBe("conflict");
  });

  it("behandelt ältere Entwürfe ohne Baseline wie bisher", () => {
    expect(decideDraftRestore("Mein Text", null, "Server")).toBe("restore");
  });
});

describe("createTextDraftStore (T3)", () => {
  it("benachrichtigt nur die Abonnenten des geänderten Blocks", () => {
    const store = createTextDraftStore({ a: "eins", b: "zwei" });
    const onA = vi.fn();
    const onB = vi.fn();
    store.subscribe("a", onA);
    store.subscribe("b", onB);
    store.set("a", "eins!");
    expect(onA).toHaveBeenCalledTimes(1);
    expect(onB).not.toHaveBeenCalled();
    store.set("a", "eins!");
    expect(onA).toHaveBeenCalledTimes(1);
    expect(store.get("a")).toBe("eins!");
    expect(store.get("neu")).toBeUndefined();
  });

  it("meldet die Leer-Signatur nur beim Wechsel leer/gefüllt", () => {
    const store = createTextDraftStore({ a: "", b: "x" });
    const onEmptiness = vi.fn();
    store.subscribeEmptiness(onEmptiness);
    expect(store.getEmptinessKey()).toBe("a");
    store.set("b", "xy");
    expect(onEmptiness).not.toHaveBeenCalled();
    store.setMany([["a", "jetzt Text"], ["b", " "]]);
    expect(onEmptiness).toHaveBeenCalledTimes(1);
    expect(store.getEmptinessKey()).toBe("b");
  });
});

describe("settleDraftAfterSave", () => {
  beforeEach(() => {
    clearOfflineStore();
    localStorage.clear();
  });

  it("entfernt Entwurf und Baseline, wenn genau dieser Stand gespeichert wurde", () => {
    saveDraft("protocol-text:b1", "abc");
    saveDraft("protocol-text-base:b1", "");
    const requeue = vi.fn();
    expect(settleDraftAfterSave("protocol-text:b1", "protocol-text-base:b1", "abc", requeue)).toBe(true);
    expect(readDraft("protocol-text:b1")).toBeNull();
    expect(readDraft("protocol-text-base:b1")).toBeNull();
    expect(requeue).not.toHaveBeenCalled();
  });

  it("behält einen neueren Entwurf und stützt ihn auf den gespeicherten Stand", () => {
    // «a» landet, während schon «ab» getippt ist; danach schnelles Neuladen, bevor «ab» gesendet ist
    saveDraft("protocol-text:b1", "ab");
    saveDraft("protocol-text-base:b1", "");
    const requeue = vi.fn();
    expect(settleDraftAfterSave("protocol-text:b1", "protocol-text-base:b1", "a", requeue)).toBe(false);
    expect(readDraft("protocol-text:b1")).toBe("ab");
    expect(readDraft("protocol-text-base:b1")).toBe("a");
    expect(requeue).toHaveBeenCalledWith("ab");
    // Nach dem Neuladen zeigt der Server «a»: der Entwurf wird übernommen statt als Konflikt verworfen
    expect(decideDraftRestore(readDraft("protocol-text:b1"), readDraft("protocol-text-base:b1"), "a")).toBe("restore");
  });
});
