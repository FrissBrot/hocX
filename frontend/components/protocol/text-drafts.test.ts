import { describe, expect, it, vi } from "vitest";

import { createTextDraftStore, decideDraftRestore } from "./text-drafts";

describe("decideDraftRestore", () => {
  it("übernimmt nichts ohne oder mit identischem Entwurf", () => {
    expect(decideDraftRestore(null, null, "Server")).toBe("none");
    expect(decideDraftRestore("Server", "alt", "Server")).toBe("none");
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
