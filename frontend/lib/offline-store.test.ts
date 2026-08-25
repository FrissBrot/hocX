import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearDraft,
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
});
