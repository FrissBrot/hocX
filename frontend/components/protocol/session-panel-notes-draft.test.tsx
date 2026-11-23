import { act, fireEvent, render, screen } from "@testing-library/react";
import { createRef } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { clearOfflineStore, flushPendingOfflineWrites, queueMutation, readDraft, saveDraft } from "@/lib/offline-store";
import type { ProtocolSummary } from "@/types/api";

const apiFetch = vi.fn();
const showToast = vi.fn();
vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return { ...actual, browserApiFetch: (...args: unknown[]) => apiFetch(...args) };
});
vi.mock("@/contexts/toast-context", () => ({ useToast: () => showToast }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import { SessionPanel, type SessionPanelHandle } from "./session-panel";

// Sitzungsnotizen nach schnellem Neuladen: lokaler Entwurf vs. Serverstand (Fix 1.6)

const KEY = "protocol-notes:p-1";
const BASE = "protocol-notes-base:p-1";

function outbox(): Array<{ key: string; body: string }> {
  flushPendingOfflineWrites();
  return JSON.parse(localStorage.getItem("hocx-offline-outbox-v1") ?? "[]");
}

function open(sessionNotes: string) {
  const ref = createRef<SessionPanelHandle>();
  const protocol = { id: "p-1", session_notes: sessionNotes } as unknown as ProtocolSummary;
  render(<SessionPanel ref={ref} protocol={protocol} participants={[]} />);
  act(() => ref.current?.openNotes(false));
  return screen.getByPlaceholderText(/Notizen zur Sitzung/) as HTMLTextAreaElement;
}

beforeEach(() => {
  clearOfflineStore();
  localStorage.clear();
  apiFetch.mockReset();
  showToast.mockReset();
  Object.defineProperty(navigator, "onLine", { configurable: true, value: false });
});

describe("Sitzungsnotizen: lokaler Entwurf nach dem Neuladen", () => {
  it("zeigt einen noch nicht gespeicherten Entwurf (nicht wieder den alten Serverstand)", () => {
    saveDraft(KEY, "Neu getippt");
    saveDraft(BASE, "Server alt");
    const notes = open("Server alt");
    expect(notes.value).toBe("Neu getippt");
    expect(showToast).toHaveBeenCalledWith(expect.stringMatching(/wiederhergestellt/), "info");
  });

  it("stellt einen alten Entwurf nicht über neuere Notizen", () => {
    saveDraft(KEY, "Mein alter Entwurf");
    saveDraft(BASE, "Stand vorher");
    const notes = open("Neuere Fassung von B");
    expect(notes.value).toBe("Neuere Fassung von B");
    expect(showToast).toHaveBeenCalledWith(expect.stringMatching(/nicht übernommen/), "error", expect.anything());
    // Der Entwurf bleibt erhalten (übernehmen auf Wunsch)
    expect(readDraft(KEY)).toBe("Mein alter Entwurf");
  });

  it("räumt einen schon gespeicherten Entwurf samt Outbox-Eintrag auf", () => {
    saveDraft(KEY, "Gespeichert");
    saveDraft(BASE, "");
    queueMutation({ key: KEY, path: "/api/protocols/p-1", method: "PATCH", body: JSON.stringify({ session_notes: "Gespeichert", expected_session_notes: "" }) });
    const notes = open("Gespeichert");
    expect(notes.value).toBe("Gespeichert");
    expect(readDraft(KEY)).toBeNull();
    expect(readDraft(BASE)).toBeNull();
    expect(outbox().filter((item) => item.key === KEY)).toEqual([]);
    expect(showToast).not.toHaveBeenCalled();
  });

  it("verliert beim Speichern keinen inzwischen weiter getippten Text", async () => {
    vi.useFakeTimers();
    try {
      let resolveSave: (value: unknown) => void = () => {};
      apiFetch.mockImplementation(() => new Promise((resolve) => { resolveSave = resolve; }));
      const notes = open("");
      act(() => { notes.focus(); });
      fireEvent.change(notes, { target: { value: "a" } });
      await act(async () => { vi.advanceTimersByTime(600); });
      expect(apiFetch).toHaveBeenCalledTimes(1);
      // Während «a» gespeichert wird, weiter tippen
      fireEvent.change(notes, { target: { value: "ab" } });
      await act(async () => { resolveSave({ session_notes: "a" }); });
      // Neuladen jetzt: «ab» muss als Entwurf auf Basis «a» bereitliegen
      expect(readDraft(KEY)).toBe("ab");
      expect(readDraft(BASE)).toBe("a");
      const queued = outbox().find((item) => item.key === KEY);
      expect(queued && JSON.parse(queued.body)).toEqual({ session_notes: "ab", expected_session_notes: "a" });
    } finally {
      vi.useRealTimers();
    }
  });
});
