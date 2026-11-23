import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { ProtocolSummary } from "@/types/api";

vi.mock("@/lib/api/client", () => ({ browserApiFetch: vi.fn() }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import { SessionPanel } from "./session-panel";

// Nicht sichtbare Teile der Schublade (Notizen bzw. Pendenz) sind `hidden`: ihre Felder dürfen
// nicht in der Tab-Reihenfolge bleiben. Im abgeschlossenen Protokoll sind Notizen nur lesbar.

const protocol = { id: "p-1", session_notes: "Raum reservieren" } as unknown as ProtocolSummary;

it("hält verborgene Teile aus der Tab-Reihenfolge", () => {
  const { container } = render(<SessionPanel protocol={protocol} participants={[]} active="notes" onClose={vi.fn()} />);
  expect(container.querySelector(".session-panel-todo-wrap")?.hasAttribute("hidden")).toBe(true);
  expect(container.querySelector(".session-panel-notes-wrap")?.hasAttribute("hidden")).toBe(false);
});

it("zeigt die Notizen im abgeschlossenen Protokoll nur lesend und ohne Pendenz", () => {
  const { container } = render(<SessionPanel protocol={protocol} participants={[]} active="notes" onClose={vi.fn()} readOnly />);
  expect((screen.getByRole("textbox", { name: "Sitzungsnotizen" }) as HTMLTextAreaElement).readOnly).toBe(true);
  expect(container.querySelector(".session-panel-todo-wrap")).toBeNull();
});
