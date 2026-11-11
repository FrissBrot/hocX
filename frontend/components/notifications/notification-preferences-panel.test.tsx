import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ browserApiFetch: (url: string, init?: { method?: string; body?: string }) => api(url, init) }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => vi.fn() }));

import { NotificationPreferencesPanel } from "./notification-preferences-panel";

const loaded = {
  preferences: [{ category: "todo_new", enabled: true }, { category: "todo_reminders", enabled: true }],
  has_email: true,
  email_enabled: true,
};

beforeEach(() => {
  vi.clearAllMocks();
  api.mockImplementation((_url: string, init?: { method?: string; body?: string }) =>
    Promise.resolve(init?.method === "PUT"
      ? { ...loaded, preferences: [{ category: "todo_new", enabled: true }, { category: "todo_reminders", enabled: false }] }
      : loaded));
});

it("saves a switch immediately", async () => {
  render(<NotificationPreferencesPanel open />);
  const reminders = await screen.findByRole("switch", { name: /Erinnerungen an Aufgaben/ });
  fireEvent.click(reminders);
  await waitFor(() => expect(reminders).not.toBeChecked());
  const put = api.mock.calls.find(([, init]) => init?.method === "PUT");
  expect(JSON.parse(put![1].body)).toEqual({ preferences: [{ category: "todo_reminders", enabled: false }] });
});

it("explains missing email and disabled platform delivery", async () => {
  api.mockResolvedValue({ ...loaded, has_email: false, email_enabled: false });
  render(<NotificationPreferencesPanel open />);
  expect(await screen.findByText(/keine E-Mail-Adresse/)).toBeInTheDocument();
  expect(screen.getByText(/noch nicht eingerichtet/)).toBeInTheDocument();
});
