import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { ProtocolSummary } from "@/types/api";

vi.mock("@/lib/api/client", () => ({ browserApiFetch: vi.fn() }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => vi.fn() }));

import { CollaborationStatusPanel } from "./collaboration-status-panel";
import { SessionPanel } from "./session-panel";

// Geschlossene Schnellmenü-Flyouts sind nur per CSS (opacity 0, pointer-events none) versteckt.
// Ohne `inert` bleiben ihre Felder und Buttons in der Tab-Reihenfolge: Tastaturnutzer landen in
// unsichtbaren Feldern und können sogar «Protokoll abschliessen» unsichtbar auslösen.

it("takes the closed status panel (with its close CTA) out of the tab order", () => {
  const props = {
    onClose: vi.fn(),
    protocolNumber: "P-1",
    modeLabel: "Sitzung",
    attendanceTally: null,
    otherPresence: [],
    connected: true,
    ctaLabel: "Protokoll abschliessen",
    onCta: vi.fn(),
  };
  const { rerender } = render(<CollaborationStatusPanel open={false} {...props} />);
  const dialog = screen.getByRole("dialog", { hidden: true });
  expect(dialog.hasAttribute("inert")).toBe(true);

  rerender(<CollaborationStatusPanel open {...props} />);
  expect(screen.getByRole("dialog").hasAttribute("inert")).toBe(false);
  expect(screen.getByRole("button", { name: "Protokoll abschliessen" })).toBeTruthy();
});

it("takes the closed notes and quick-todo flyouts out of the tab order", () => {
  const protocol = { id: "p-1", session_notes: "" } as unknown as ProtocolSummary;
  const { container } = render(<SessionPanel protocol={protocol} participants={[]} />);
  const flyouts = Array.from(container.querySelectorAll(".quick-flyout"));
  expect(flyouts).toHaveLength(2);
  for (const flyout of flyouts) {
    expect(flyout.hasAttribute("inert")).toBe(true);
  }
});
