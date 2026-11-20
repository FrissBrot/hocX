import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => vi.fn());
const confirm = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ browserApiFetch: (url: string, init?: { method?: string }) => api(url, init) }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => vi.fn() }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => confirm }));

import { SessionsPanel } from "./sessions-panel";

const list = {
  sessions: [
    { id: "a", current: true, user_agent_family: "Firefox · Linux", host: "app.example.com", created_at: "2026-11-20T08:00:00Z", last_seen_at: "2026-11-20T09:00:00Z", mfa: true, via_bridge: false },
    { id: "b", current: false, user_agent_family: "Safari · iOS", host: "app.example.com", created_at: "2026-11-19T08:00:00Z", last_seen_at: "2026-11-19T09:00:00Z", mfa: true, via_bridge: false },
  ],
  legacy_session: false,
};

beforeEach(() => {
  vi.clearAllMocks();
  confirm.mockResolvedValue(true);
  api.mockImplementation((url: string, init?: { method?: string }) =>
    Promise.resolve(init?.method === "POST" ? { revoked: 1 } : init?.method === "DELETE" ? null : list));
});

it("lists devices and signs out a single other device", async () => {
  render(<SessionsPanel open />);
  expect(await screen.findByText("Safari · iOS")).toBeInTheDocument();
  expect(screen.getByText("Dieses Gerät")).toBeInTheDocument();
  // Nur das andere Gerät hat «Abmelden»
  const buttons = screen.getAllByRole("button", { name: "Abmelden" });
  expect(buttons).toHaveLength(1);
  fireEvent.click(buttons[0]);
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/users/me/sessions/b", { method: "DELETE" }));
});

it("signs out all other devices after confirmation", async () => {
  render(<SessionsPanel open />);
  await screen.findByText("Safari · iOS");
  fireEvent.click(screen.getByRole("button", { name: "Alle anderen Geräte abmelden" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/users/me/sessions/revoke-others", { method: "POST" }));
  expect(confirm).toHaveBeenCalledWith(expect.objectContaining({ tone: "danger" }));
});
