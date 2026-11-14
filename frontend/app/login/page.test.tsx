import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return { ...actual, browserApiFetch: (url: string, init?: { method?: string; body?: string }) => api(url, init) };
});
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn(), refresh: vi.fn() }) }));
vi.mock("@/lib/maintenance", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/maintenance")>();
  return { ...actual, useMaintenanceStatus: () => ({ status: null, loaded: true }) };
});
vi.mock("@/lib/webauthn", () => ({
  browserSupportsPasskeys: () => false,
  createPasskeyCredential: vi.fn(),
  getPasskeyAssertion: vi.fn(),
}));

import { ApiError } from "@/lib/api/client";
import LoginPage from "./page";

const PENDING_TOTP = {
  status: "verification_required",
  ticket: "ticket-1",
  required: false,
  user_display_name: "Test Person",
  user_email: "person@example.com",
  tenant_name: "Pfadi Test",
  available_methods: [{ factor_type: "totp", label: "Auth App" }],
  default_factor_type: "totp",
  default_factor_label: "Auth App",
  can_add_totp: false,
  can_add_passkey: false,
};

beforeEach(() => {
  vi.clearAllMocks();
});

async function loginUntilTotp() {
  render(<LoginPage />);
  fireEvent.change(screen.getByLabelText("E-Mail"), { target: { value: "person@example.com" } });
  fireEvent.change(screen.getByLabelText("Passwort"), { target: { value: "ein-langes-passwort" } });
  fireEvent.click(screen.getByRole("button", { name: "Einloggen" }));
  const firstDigit = await screen.findByLabelText("Code-Ziffer 1");
  fireEvent.change(firstDigit, { target: { value: "123456" } });
  fireEvent.click(screen.getByRole("button", { name: "Bestätigen" }));
}

it("shows a wrong TOTP code in the UI language instead of the raw backend text", async () => {
  api.mockImplementation((url: string) => {
    if (url === "/api/auth/login") return Promise.resolve({ authenticated: false, mfa: PENDING_TOTP });
    if (url === "/api/auth/mfa/totp/verify") {
      return Promise.reject(new ApiError("ROHER BACKEND-TEXT", "auth", 401, { code: "totp_invalid", message: "ROHER BACKEND-TEXT" }));
    }
    return Promise.resolve(null);
  });

  await loginUntilTotp();

  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Der Code ist nicht gültig. Bitte prüfe die Uhrzeit deines Geräts und versuche es erneut."));
  expect(screen.queryByText("ROHER BACKEND-TEXT")).not.toBeInTheDocument();
});

it("shows a disabled login in the UI language", async () => {
  api.mockImplementation((url: string) => {
    if (url === "/api/auth/login") {
      return Promise.reject(new ApiError("ROHER BACKEND-TEXT", "auth", 403, { code: "login_disabled", message: "ROHER BACKEND-TEXT" }));
    }
    return Promise.resolve(null);
  });

  render(<LoginPage />);
  fireEvent.change(screen.getByLabelText("E-Mail"), { target: { value: "person@example.com" } });
  fireEvent.change(screen.getByLabelText("Passwort"), { target: { value: "ein-langes-passwort" } });
  fireEvent.click(screen.getByRole("button", { name: "Einloggen" }));

  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Die Anmeldung ist für dieses Konto deaktiviert."));
});
