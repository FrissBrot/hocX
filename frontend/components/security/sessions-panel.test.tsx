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

const devices = [
  { id: "d1", user_agent_family: "Firefox · Linux", created_at: "2026-11-01T08:00:00Z", last_seen_at: "2026-11-20T09:00:00Z", current: true },
];

beforeEach(() => {
  vi.clearAllMocks();
  confirm.mockResolvedValue(true);
  api.mockImplementation((url: string, init?: { method?: string }) =>
    Promise.resolve(init?.method === "POST" ? { revoked: 1 } : init?.method === "DELETE" ? null : url.endsWith("/devices") ? devices : list));
});

it("lists devices and signs out a single other device", async () => {
  render(<SessionsPanel open />);
  expect(await screen.findByText("Safari · iOS")).toBeInTheDocument();
  expect(screen.getAllByText("Dieses Gerät").length).toBeGreaterThan(0);
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

it("forgets a known device", async () => {
  render(<SessionsPanel open />);
  await screen.findByText("Bekannte Geräte");
  fireEvent.click(await screen.findByRole("button", { name: "Vergessen" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/users/me/devices/d1", { method: "DELETE" }));
});

it("shows the translated country and the DB-IP attribution only when a country is known", async () => {
  api.mockImplementation((url: string) =>
    Promise.resolve(url.endsWith("/devices") ? devices : { ...list, sessions: [{ ...list.sessions[1], country: "CH" }] }));
  render(<SessionsPanel open />);
  expect(await screen.findByText("Land: Schweiz")).toBeInTheDocument();
  const source = screen.getByRole("link", { name: /DB-IP\.com/ });
  expect(source).toHaveAttribute("href", "https://db-ip.com");
  expect(source).toHaveAttribute("rel", "noopener noreferrer");
});

it("shows no attribution without any country", async () => {
  render(<SessionsPanel open />);
  await screen.findByText("Safari · iOS");
  expect(screen.queryByRole("link", { name: /DB-IP\.com/ })).not.toBeInTheDocument();
});
