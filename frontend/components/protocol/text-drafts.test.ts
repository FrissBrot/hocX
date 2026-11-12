import { describe, expect, it } from "vitest";

import { decideDraftRestore } from "./text-drafts";

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
