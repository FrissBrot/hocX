import { StrictMode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ browserApiFetch: (url: string, init?: { method?: string; body?: string }) => api(url, init) }));

import SetPasswordPage from "./page";

const PASSWORD = "ein-sehr-langes-passwort";

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/auth/set-password#token=abc123");
  api.mockImplementation((url: string) =>
    Promise.resolve(url.endsWith("/preview")
      ? { purpose: "invite", display_name: "Neu Person", email: "neu@example.com", tenant_name: "Pfadi Test" }
      : { purpose: "invite" }));
});

it("reads the token from the fragment, removes it from the address bar and sends it only in the body", async () => {
  render(<SetPasswordPage />);
  expect(await screen.findByRole("heading", { name: "Konto einrichten" })).toBeInTheDocument();
  expect(window.location.hash).toBe("");
  expect(api).toHaveBeenCalledWith("/api/auth/account-link/preview", { method: "POST", body: JSON.stringify({ token: "abc123" }) });
});

it("enables saving only for a long enough, repeated password", async () => {
  render(<SetPasswordPage />);
  const [password, repeat] = await screen.findAllByLabelText(/Passwort/);
  const submit = screen.getByRole("button", { name: "Konto einrichten" });
  fireEvent.change(password, { target: { value: "kurz" } });
  expect(screen.getByText(/Noch zu kurz/)).toBeInTheDocument();
  fireEvent.change(password, { target: { value: PASSWORD } });
  fireEvent.change(repeat, { target: { value: `${PASSWORD}x` } });
  expect(submit).toBeDisabled();
  fireEvent.change(repeat, { target: { value: PASSWORD } });
  expect(submit).toBeEnabled();
  fireEvent.click(submit);
  await waitFor(() => expect(screen.getByText(/Konto ist eingerichtet/)).toBeInTheDocument());
  expect(api).toHaveBeenCalledWith("/api/auth/account-link/complete", { method: "POST", body: JSON.stringify({ token: "abc123", password: PASSWORD }) });
});

it("shows an invalid link without a token", async () => {
  window.history.replaceState(null, "", "/auth/set-password");
  render(<SetPasswordPage />);
  expect(await screen.findByText(/ungültig, abgelaufen/)).toBeInTheDocument();
  expect(api).not.toHaveBeenCalled();
});

it("keeps the token under React StrictMode (effects run twice in development)", async () => {
  render(<StrictMode><SetPasswordPage /></StrictMode>);
  expect(await screen.findByRole("heading", { name: "Konto einrichten" })).toBeInTheDocument();
  expect(await screen.findAllByLabelText(/Passwort/)).toHaveLength(2);
  expect(screen.queryByText(/ungültig, abgelaufen/)).not.toBeInTheDocument();
  expect(window.location.hash).toBe("");
});
