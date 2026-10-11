import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { NextSessionInfo, ProtocolSummary } from "@/types/api";
import { DashboardView } from "./dashboard-view";

const api = vi.hoisted(() => vi.fn());
const toast = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/lib/api/client", () => ({ browserApiFetch: api }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));

const sessions: NextSessionInfo[] = [0, 1].map((index) => ({
  protocol: { id: `protocol-${index}`, title: `Sitzung ${index}`, protocol_number: `2026.${index}`, protocol_date: `2026-10-${12 + index}` } as ProtocolSummary,
  attendance_block_id: `block-${index}`,
  entries: [{ participant_id: "person", participant_name: "Alex", status: "absent" }],
}));
function mount(upcomingSessions = sessions, canExcuse = true) {
  render(<DashboardView todos={[]} fines={[]} upcomingSessions={upcomingSessions} canExcuse={canExcuse} canWrite={canExcuse} hasProtocols canConfigure={false} />);
}
beforeEach(() => { vi.clearAllMocks(); api.mockResolvedValue({}); });

it("hides next-session label and excuse widgets when no future session exists", () => {
  mount([]);
  expect(screen.queryByText("Nächste Sitzung")).not.toBeInTheDocument();
  expect(screen.queryByText("Teilnehmer entschuldigen")).not.toBeInTheDocument();
  expect(screen.getByText("Keine anstehende Sitzung geplant")).toBeInTheDocument();
});
it("labels each attendance widget and excuses only its protocol", async () => {
  mount();
  const chips = screen.getAllByRole("button", { name: /Alex/ });
  const card = chips[1].closest("section")!;
  expect(within(card).getByText("Sitzung 1")).toBeInTheDocument();
  expect(within(card).getByText(/13.10.2026/)).toBeInTheDocument();
  fireEvent.click(chips[1]);
  expect(api).toHaveBeenCalledWith("/api/protocols/protocol-1/attendance/person/excuse", expect.objectContaining({ body: '{"excused":true}' }));
  await waitFor(() => expect(chips[1]).toBeEnabled());
  expect(chips[1]).toHaveAttribute("aria-pressed", "true");
  expect(chips[0]).toHaveAttribute("aria-pressed", "false");
});
it("reverts only the affected protocol and reports failed updates", async () => {
  api.mockRejectedValueOnce(new Error("Fehler"));
  mount();
  fireEvent.click(screen.getAllByRole("button", { name: /Alex/ })[1]);
  await waitFor(() => expect(toast).toHaveBeenCalledWith("Fehler", "error"));
  expect(screen.getAllByRole("button", { name: /Alex/ }).every((chip) => chip.getAttribute("aria-pressed") === "false")).toBe(true);
});
it("prevents readers from changing attendance", () => {
  mount(sessions, false);
  screen.getAllByRole("button", { name: /Alex/ }).forEach((chip) => expect(chip).toBeDisabled());
});
it("removes attendance widgets when refreshed session data becomes empty", async () => {
  const props = { todos: [], fines: [], canExcuse: true, canWrite: true, hasProtocols: true, canConfigure: false };
  const { rerender } = render(<DashboardView {...props} upcomingSessions={sessions} />);
  expect(screen.getAllByRole("button", { name: /Alex/ })).toHaveLength(2);
  rerender(<DashboardView {...props} upcomingSessions={[]} />);
  await waitFor(() => expect(screen.queryByRole("button", { name: /Alex/ })).not.toBeInTheDocument());
  expect(screen.queryByText("Nächste Sitzung")).not.toBeInTheDocument();
});
