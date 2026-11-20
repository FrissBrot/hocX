import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { EventSummary } from "@/types/api";

vi.mock("@/lib/api/client", () => ({ browserApiFetch: vi.fn() }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => vi.fn() }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn().mockResolvedValue(true) }));
vi.mock("@/components/events/event-dialog", () => ({
  EventDialog: ({ event }: { event: EventSummary }) => <div data-testid="event-detail">{event.title}</div>,
}));

import { EventOverviewModal } from "./event-overview-modal";

const event = {
  id: "e-1",
  event_date: "2026-12-01",
  event_end_date: null,
  tag: "Hock",
  title: "Chlausabend",
  description: null,
  cycle_assignments: [],
} as unknown as EventSummary;

// Die Zeilen der Terminübersicht öffnen die Termindetails nur per Mausklick (`tr onClick`).
// Per Tastatur gab es keinen Weg zu den Details eines bestehenden Termins.
it("opens the event details from a keyboard-reachable control in each row", () => {
  render(
    <EventOverviewModal
      open
      onClose={vi.fn()}
      protocolId="p-1"
      forcedTag="Hock"
      allowEndDate={false}
      protocolDate="2026-11-18"
      visibleEvents={[event]}
      availableParticipants={[]}
      knownEventTags={["Hock"]}
      tagConfig={{}}
      onTagColorChange={vi.fn()}
      onTagRename={vi.fn()}
      onCreateEvent={vi.fn()}
      onUpdateEvent={vi.fn()}
      onDeleteEvent={vi.fn()}
    />,
  );
  const opener = screen.getByRole("button", { name: "Chlausabend" });
  expect(screen.queryByTestId("event-detail")).toBeNull();
  fireEvent.click(opener);
  expect(screen.getByTestId("event-detail").textContent).toBe("Chlausabend");
});
