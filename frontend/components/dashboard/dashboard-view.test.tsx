import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { AttendanceFineListItem, NextSessionInfo, ProtocolSummary } from "@/types/api";
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
const access = (role: string, features: string[] = []) => ({ role, features });
function mount(upcomingSessions = sessions, canExcuse = true) {
  render(<DashboardView todos={[]} fines={[]} upcomingSessions={upcomingSessions} access={access(canExcuse ? "writer" : "reader")} hasProtocols />);
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
  // Nur der Entschuldigen-Request schlaegt fehl, nicht das Nachladen von Todos/Terminen beim Mount.
  api.mockImplementation((path: string) => (path.includes("/excuse") ? Promise.reject(new Error("Fehler")) : Promise.resolve({})));
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
  const props = { todos: [], fines: [], access: access("writer"), hasProtocols: true };
  const { rerender } = render(<DashboardView {...props} upcomingSessions={sessions} />);
  expect(screen.getAllByRole("button", { name: /Alex/ })).toHaveLength(2);
  rerender(<DashboardView {...props} upcomingSessions={[]} />);
  await waitFor(() => expect(screen.queryByRole("button", { name: /Alex/ })).not.toBeInTheDocument());
  expect(screen.queryByText("Nächste Sitzung")).not.toBeInTheDocument();
});

const fine = { id: "f1", protocol_id: "p1", participant_id: "x", participant_name_snapshot: "Alex", fine_type: "late", amount: 5, status: "pending", currency_label: "CHF" } as AttendanceFineListItem;
it("labels fines as the reader's own and hides the people count", () => {
  render(<DashboardView todos={[]} fines={[fine]} upcomingSessions={[]} access={access("reader", ["finance"])} hasProtocols />);
  expect(screen.getByText("Meine offenen Bussen")).toBeInTheDocument();
  expect(screen.queryByText("1 Person")).not.toBeInTheDocument();
});
it("shows all open fines with people count and loads account balances for cashiers", async () => {
  render(<DashboardView todos={[]} fines={[fine]} upcomingSessions={[]} access={access("kassier", ["finance"])} hasProtocols />);
  expect(screen.getByText("Offene Bussen")).toBeInTheDocument();
  expect(screen.getByText("1 Person")).toBeInTheDocument();
  expect(screen.getByText("Kontostände")).toBeInTheDocument();
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/finance/accounts"));
});
it("hides finance and submission tiles when the features are not booked", () => {
  render(<DashboardView todos={[]} fines={[]} upcomingSessions={[]} access={access("admin")} hasProtocols />);
  expect(screen.queryByText("Offene Bussen")).not.toBeInTheDocument();
  expect(screen.queryByText("Kontostände")).not.toBeInTheDocument();
  expect(screen.queryByText("Abgaben mit Frist")).not.toBeInTheDocument();
  expect(screen.getByText("Meine Todos")).toBeInTheDocument();
  expect(screen.getByText("Kommende Termine")).toBeInTheDocument();
});
