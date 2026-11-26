import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { ProtocolSummary } from "@/types/api";

const api = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), back: vi.fn(), refresh: vi.fn() }) }));
vi.mock("@/lib/api/client", () => ({
  ApiError: class ApiError extends Error {},
  browserApiFetch: (url: string, init?: unknown) => api(url, init),
}));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => vi.fn() }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn().mockResolvedValue(true) }));
vi.mock("@/components/mobile/mobile-shell", () => ({ useMobileSession: () => ({ user: { id: "u-1", display: "Aktuar" } }) }));
vi.mock("@/lib/hooks/use-pdf-export", () => ({ usePdfExport: () => ({ busyByProtocol: {}, openOrGeneratePdf: vi.fn() }) }));
vi.mock("@/lib/hooks/use-protocol-collaboration", () => ({
  useProtocolCollaboration: () => ({
    hasOtherActiveEditors: () => false,
    otherPresence: [],
    isLockedByOther: () => false,
    lockField: vi.fn(),
    unlockField: vi.fn(),
    onFieldUpdate: () => () => {},
    onStatusChanged: () => () => {},
    sendFieldUpdate: vi.fn(),
    sendStatusChanged: vi.fn(),
  }),
  useFieldLocks: () => ({}),
}));

import { MobileProtocolEditor } from "./mobile-protocol-editor";

function renderEditor(status: string) {
  api.mockResolvedValue([]);
  const protocol = {
    id: "p-1",
    protocol_number: "P-7",
    title: "Hock",
    status,
    session_notes: "Kassier fehlt",
    template_id: "t-1",
    protocol_date: "2026-11-18",
  } as unknown as ProtocolSummary;
  const view = render(
    <MobileProtocolEditor
      protocol={protocol}
      initialElements={[]}
      initialTodos={{}}
      initialImages={{}}
      availableParticipants={[]}
      availableAccounts={[]}
      initialFinanceTransactions={{}}
      initialPendingTodos={[]}
      forceReadOnly={false}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Notizen" }));
  return Object.assign(screen.getByRole("textbox", { name: "Sitzungsnotizen" }) as HTMLTextAreaElement, { unmountEditor: view.unmount });
}

// Abgeschlossene Protokolle sind eingefroren (Backend: 409 auf session_notes). Mobil liess das
// Notiz-Blatt trotzdem bearbeiten: getippter Text scheiterte erst beim Speichern.
it("shows the session notes of a finalized protocol read-only", () => {
  expect(renderEditor("abgeschlossen").readOnly).toBe(true);
});

it("keeps the session notes editable while the protocol is open", () => {
  expect(renderEditor("durchgeführt").readOnly).toBe(false);
});

// Collaboration-Audit F-09: die Unmount-Bereinigung löschte nur den Timer, die letzten ~800 ms
// Eingabe gingen bei Navigation oder Wechsel Desktop/Mobil ohne Hinweis verloren.
it("saves pending session notes immediately when the editor unmounts", () => {
  const notes = renderEditor("durchgeführt");
  api.mockClear();
  fireEvent.change(notes, { target: { value: "Kassier fehlt, Revisor auch" } });
  expect(api).not.toHaveBeenCalled();
  notes.unmountEditor();
  const patches = api.mock.calls.filter(([url, init]) => url === "/api/protocols/p-1" && (init as RequestInit | undefined)?.method === "PATCH");
  expect(patches).toHaveLength(1);
  expect(JSON.parse(String((patches[0][1] as RequestInit).body))).toEqual({
    session_notes: "Kassier fehlt, Revisor auch",
    expected_session_notes: "Kassier fehlt",
  });
});

it("closing the notes sheet saves only once", () => {
  const notes = renderEditor("durchgeführt");
  api.mockClear();
  fireEvent.change(notes, { target: { value: "Neu" } });
  fireEvent.click(screen.getByRole("button", { name: "Schliessen" }));
  notes.unmountEditor();
  const patches = api.mock.calls.filter(([url, init]) => url === "/api/protocols/p-1" && (init as RequestInit | undefined)?.method === "PATCH");
  expect(patches).toHaveLength(1);
});
