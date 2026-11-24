import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({
  ApiError: class ApiError extends Error {},
  browserApiFetch: (url: string, init?: { method?: string; body?: string }) => api(url, init),
}));
vi.mock("@/lib/webauthn", () => ({ browserSupportsPasskeys: () => false, getPasskeyAssertion: vi.fn() }));

import { StepUpDialog } from "./step-up-dialog";

beforeEach(() => {
  vi.clearAllMocks();
});

it("asks for the app code and confirms the step-up", async () => {
  api.mockImplementation((url: string, init?: { method?: string }) =>
    Promise.resolve(init?.method === "POST" ? { auth_time: "2026-11-20T10:00:00Z" } : { methods: ["totp", "passkey"], auth_time: null }));
  const done = vi.fn();
  render(<StepUpDialog open onDone={done} />);
  const input = await screen.findByLabelText(/Code aus der Authenticator-App/);
  // Passkey wird ohne Browser-Unterstützung nicht angeboten - keine Auswahl
  expect(screen.queryByRole("tab", { name: "Passkey" })).not.toBeInTheDocument();
  const confirm = screen.getByRole("button", { name: "Bestätigen" });
  expect(confirm).toBeDisabled();
  fireEvent.change(input, { target: { value: "12a3456" } });
  expect(input).toHaveValue("123456");
  fireEvent.click(confirm);
  await waitFor(() => expect(done).toHaveBeenCalledWith(true));
  const post = api.mock.calls.find(([, init]) => init?.method === "POST");
  expect(post![0]).toBe("/api/auth/step-up");
  expect(JSON.parse(post![1].body)).toEqual({ method: "totp", code: "123456" });
});

it("uses the password for accounts without factor and shows errors", async () => {
  api.mockImplementation((_url: string, init?: { method?: string }) =>
    init?.method === "POST"
      ? Promise.reject(new Error("Passwort ist nicht korrekt"))
      : Promise.resolve({ methods: ["password"], auth_time: null }));
  const done = vi.fn();
  render(<StepUpDialog open onDone={done} />);
  fireEvent.change(await screen.findByLabelText(/Dein Passwort/), { target: { value: "falsch" } });
  fireEvent.click(screen.getByRole("button", { name: "Bestätigen" }));
  expect(await screen.findByText("Passwort ist nicht korrekt")).toBeInTheDocument();
  expect(done).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Abbrechen" }));
  expect(done).toHaveBeenCalledWith(false);
});

it("explains when no confirmation is possible here instead of loading forever", async () => {
  // Konto nur mit Passkey, aber hier nicht nutzbar (Vereins-Domain bzw. Browser ohne Passkeys):
  // das Backend bzw. der Browserfilter lässt keine Methode übrig.
  api.mockResolvedValue({ methods: ["passkey"], auth_time: null });
  const done = vi.fn();
  render(<StepUpDialog open onDone={done} />);
  expect(await screen.findByText(/keine Bestätigung möglich/)).toBeInTheDocument();
  expect(screen.queryByText("Wird geladen …")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Bestätigen" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Abbrechen" }));
  expect(done).toHaveBeenCalledWith(false);
});
