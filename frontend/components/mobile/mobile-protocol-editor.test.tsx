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
  render(
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
  return screen.getByRole("textbox", { name: "Sitzungsnotizen" }) as HTMLTextAreaElement;
}

// Abgeschlossene Protokolle sind eingefroren (Backend: 409 auf session_notes). Mobil liess das
// Notiz-Blatt trotzdem bearbeiten: getippter Text scheiterte erst beim Speichern.
it("shows the session notes of a finalized protocol read-only", () => {
  expect(renderEditor("abgeschlossen").readOnly).toBe(true);
});

it("keeps the session notes editable while the protocol is open", () => {
  expect(renderEditor("durchgeführt").readOnly).toBe(false);
});
